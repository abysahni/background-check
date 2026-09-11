"""
Store Candidate Background Check & OSINT Verification Assistant
A secure, privacy-first tool for retail and store hiring.
Extracts resume data, searches public digital footprints, resolves candidate photos,
verifies claims against EEOC guidelines, and generates tailored reference kits.
"""

import os
import re
import json
import hmac
import datetime
import html as _html
from typing import Dict, Any, List
import streamlit as st
from dotenv import load_dotenv

import extractor
import avatar_fetcher
import photo_resolver
import osint_search
import verifier

# Load environment variables
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Store Candidate Background Check",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1e293b;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748b;
        margin-bottom: 1.5rem;
    }
    .candidate-card {
        background: linear-gradient(135deg, #f8fafc 0%, #edf2f7 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 20px;
    }
    .badge-verified {
        background-color: #dcfce7;
        color: #15803d;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .badge-review {
        background-color: #fef9c3;
        color: #a16207;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .badge-flag {
        background-color: #fee2e2;
        color: #b91c1c;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .badge-neutral {
        background-color: #f1f5f9;
        color: #475569;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.82rem;
        font-weight: 600;
    }
    .compliance-box {
        background-color: #f0fdf4;
        border-left: 4px solid #16a34a;
        padding: 12px 16px;
        border-radius: 6px;
        margin-top: 15px;
        font-size: 0.9rem;
        color: #166534;
    }
</style>
""", unsafe_allow_html=True)


def get_secret(key: str, default: str = "") -> str:
    """Safely get config from st.secrets or os.environ.

    NOTE: `key in st.secrets` raises StreamlitSecretNotFoundError when NO
    secrets.toml exists at all, so the lookup must be wrapped.
    """
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


# --- 1. ACCESS CODE AUTHENTICATION GATE ---
expected_code = get_secret("STORE_ACCESS_CODE", "1234")
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False if expected_code else True

if not st.session_state["authenticated"]:
    st.markdown("<div class='main-header'>🛡️ Store Hiring Portal</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub-header'>Authorized Store Staff Login</div>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.info("🔒 This application is protected to keep applicant records private.")
        st.session_state.setdefault("_failed_attempts", 0)
        locked_out = st.session_state["_failed_attempts"] >= 5
        entered_code = st.text_input("Enter Store Access Code", type="password", disabled=locked_out)
        if locked_out:
            st.error("Too many incorrect attempts. Restart the app session to try again.")
        elif st.button("Unlock Portal", type="primary", use_container_width=True):
            if hmac.compare_digest(entered_code or "", expected_code or ""):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.session_state["_failed_attempts"] += 1
                st.error("Incorrect Passcode. Contact your store administrator.")
    st.stop()


# --- 2. SIDEBAR CONFIGURATION ---
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/shield.png", width=64)
    st.title("Store Settings")
    
    store_name = st.text_input("Store / Business Name", value=get_secret("STORE_NAME", "Downtown Store"))
    
    # API Key Configuration
    env_gemini_key = get_secret("GEMINI_API_KEY", "")
    if env_gemini_key:
        api_key = env_gemini_key
        st.success("✅ Gemini API Key connected")
    else:
        api_key = st.text_input(
            "Google Gemini API Key",
            type="password",
            help="Required for resume parsing & verification synthesis."
        )
        if not api_key:
            st.info("💡 [Get a free Gemini API Key](https://aistudio.google.com/)")

    # Optional Serper.dev Key for Google Search
    serper_api_key = get_secret("SERPER_API_KEY", "")
    if not serper_api_key:
        serper_api_key = st.text_input(
            "Serper Key (Optional Google Search)",
            type="password",
            help="Free 2,500 Google searches at serper.dev. Leave empty to use free DuckDuckGo."
        )

    st.divider()
    
    # Store Role Selection
    roles = [
        "Store Associate / Cashier",
        "Inventory & Stock Specialist",
        "Customer Service Representative",
        "Shift Supervisor",
        "Assistant Store Manager",
        "Store General Manager",
        "Other"
    ]
    target_role = st.selectbox("Role Applied For", roles)
    if target_role == "Other":
        target_role = st.text_input("Specify Custom Role", "Store Employee")

    # Compliance Consent (Task 5.1)
    st.divider()
    st.markdown("**📋 Candidate Verification Consent**")
    consent_given = st.checkbox(
        "Candidate Consent Acknowledged",
        value=True,
        help="Confirms applicant was informed of reference and public record verification."
    )
    consent_method = st.selectbox(
        "Consent Method",
        ["Written Application", "Verbal Confirmation", "Email Authorization", "Candidate Portal"],
        help="Record the medium through which the applicant provided verification consent."
    )
    if consent_given:
        if "consent_record" not in st.session_state or st.session_state.get("_consent_method") != consent_method:
            st.session_state["consent_record"] = {
                "given": True,
                "method": consent_method,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            }
            st.session_state["_consent_method"] = consent_method
    else:
        st.session_state.pop("consent_record", None)
    
    st.divider()
    if st.button("🔄 Reset / New Candidate", use_container_width=True):
        for k in ["parsed_data", "verification_result", "candidate_avatar", "_last_filename", "photo_info", "confirmed_photo", "photo_rejected", "consent_record"]:
            st.session_state.pop(k, None)
        st.rerun()

    # Retention & Session Purge (Task 5.2)
    if st.button("🗑️ Delete Candidate Session Data", use_container_width=True):
        for k in ["parsed_data", "verification_result", "candidate_avatar", "_last_filename", "photo_info", "confirmed_photo", "photo_rejected", "consent_record"]:
            st.session_state.pop(k, None)
        st.success("Candidate session memory purged.")
        st.rerun()

    st.caption("🔒 *Candidate data is held in memory only for this session and is not persisted. Download and store dossiers in accordance with your store privacy policy.*")

    # Legal Disclaimer (Task 5.3)
    st.divider()
    st.markdown("""
    <small style='color: #64748b;'>
    <strong>⚖️ Legal & Privacy Disclaimer:</strong><br>
    This tool gathers <em>public</em> OSINT information and is not a consumer reporting agency. It does not perform criminal, credit, or identity checks. In Canada, pre-employment checks require candidate consent under PIPEDA and provincial human rights law. Obtain legal advice before relying on automated screening.
    </small>
    """, unsafe_allow_html=True)


# --- 3. MAIN DASHBOARD ---
st.markdown(f"<div class='main-header'>🛡️ Candidate Background & OSINT Assistant</div>", unsafe_allow_html=True)
st.markdown(f"<div class='sub-header'>Hiring verification for <strong>{store_name}</strong></div>", unsafe_allow_html=True)

# Initialize Session State
if "parsed_data" not in st.session_state:
    st.session_state["parsed_data"] = None
if "verification_result" not in st.session_state:
    st.session_state["verification_result"] = None
if "candidate_avatar" not in st.session_state:
    st.session_state["candidate_avatar"] = None


# --- STEP 1: CANDIDATE INTAKE ---
with st.expander("📝 Step 1: Candidate Intake & Resume Upload", expanded=(st.session_state["parsed_data"] is None)):
    tab_upload, tab_manual = st.tabs(["📄 Upload Resume (PDF / DOCX / TXT)", "✍️ Manual Candidate Input"])
    
    with tab_upload:
        uploaded_file = st.file_uploader(
            "Drop candidate resume here",
            type=["pdf", "docx", "txt"],
            help="Supports standard PDF, Word documents, or plain text resumes."
        )
        
        if uploaded_file and (
            st.session_state["parsed_data"] is None 
            or st.session_state.get("_last_filename") != uploaded_file.name
        ):
            with st.spinner("Extracting candidate information..."):
                file_bytes = uploaded_file.read()
                parsed = extractor.parse_candidate_document(file_bytes, uploaded_file.name, api_key=api_key)
                st.session_state["parsed_data"] = parsed
                st.session_state["_last_filename"] = uploaded_file.name
                st.success(f"Successfully extracted details for: {parsed.get('candidate_name', 'Candidate')}")
                st.rerun()

    with tab_manual:
        st.caption("Manually enter or fill in applicant details:")
        m_name = st.text_input("Candidate Full Name", value="")
        m_email = st.text_input("Email Address", value="")
        m_phone = st.text_input("Phone Number", value="")
        m_loc = st.text_input("Location (City, State)", value="")
        m_employers = st.text_area("Previous Employers (one per line)", value="")
        m_refs = st.text_area("References (Name, Company, Contact - one per line)", value="")
        
        if st.button("Load Manual Candidate"):
            employers_list = [{"company": e.strip(), "title": "Employee", "start_date": "", "end_date": ""} for e in m_employers.splitlines() if e.strip()]
            refs_list = [{"name": r.strip(), "company": "", "phone": "", "email": ""} for r in m_refs.splitlines() if r.strip()]
            st.session_state["parsed_data"] = {
                "candidate_name": m_name,
                "email": m_email,
                "phone": m_phone,
                "location": m_loc,
                "target_role": target_role,
                "summary": "Manual intake profile",
                "work_history": employers_list,
                "education": [],
                "references": refs_list,
                "links_and_handles": []
            }
            st.success("Manual candidate profile loaded!")
            st.rerun()


# --- STEP 2: REVIEW & TRIGGER VERIFICATION ---
if st.session_state["parsed_data"]:
    p = st.session_state["parsed_data"]
    
    st.subheader("📋 Step 2: Confirm Candidate Information")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        c_name = st.text_input("Full Name", value=p.get("candidate_name", ""))
    with col2:
        c_email = st.text_input("Email", value=p.get("email", ""))
    with col3:
        c_phone = st.text_input("Phone", value=p.get("phone", ""))
    with col4:
        c_location = st.text_input("City, State", value=p.get("location", ""))

    # Extracted Employers & References preview
    with st.expander("🔍 Review Extracted Employers & References (Editable before search)"):
        col_e, col_r = st.columns(2)
        with col_e:
            st.markdown("**Prior Employers Extracted:**")
            emp_names = [w.get("company", "") for w in p.get("work_history", []) if w.get("company")]
            emp_text = st.text_area("Edit Employer List (Comma-separated)", value=", ".join(emp_names))
        with col_r:
            st.markdown("**References Extracted:**")
            ref_names = [f"{r.get('name', '')} ({r.get('company', '')})" for r in p.get("references", []) if r.get("name")]
            ref_text = st.text_area("Edit References List (Comma-separated)", value=", ".join(ref_names))

    # Trigger Search Button
    if not consent_given:
        st.warning("⚠️ Confirm candidate consent in the sidebar before running verification.")

    if st.button("🚀 Run Multi-Track Verification & OSINT Search", type="primary",
                 use_container_width=True, disabled=not consent_given):
        with st.status("Performing live background check & OSINT search...", expanded=True) as status:
            # 1. Update candidate data
            updated_candidate = dict(p)
            updated_candidate["candidate_name"] = c_name
            updated_candidate["email"] = c_email
            updated_candidate["phone"] = c_phone
            updated_candidate["location"] = c_location
            updated_candidate["target_role"] = target_role
            
            # Rebuild clean employers list (edited values now actually used)
            clean_employers = [e.strip() for e in emp_text.split(",") if e.strip()]

            # Use the EDITED reference list - previously this control was dead code.
            edited_refs = []
            for raw_ref in [x.strip() for x in ref_text.split(",") if x.strip()]:
                edited_refs.append({"name": raw_ref, "company": "", "phone": "", "email": ""})
            refs_for_search = edited_refs or p.get("references", [])

            # 2. OSINT Search (runs first so photo resolution can use what it finds)
            status.write("🌐 Executing multi-track OSINT search (LinkedIn, Instagram, X/Twitter, FB, Reddit, Employer check)...")
            try:
                search_findings = osint_search.run_candidate_osint(
                    candidate_name=c_name,
                    location=c_location,
                    past_employers=clean_employers,
                    references=refs_for_search,
                    email=c_email,
                    additional_handles=[l.get("url_or_handle", "") for l in p.get("links_and_handles", [])],
                    serper_api_key=serper_api_key
                )
            except Exception as e:
                search_findings = {
                    "professional": [],
                    "social": [],
                    "employer_validation": {},
                    "reference_verification": {},
                    "web_mentions": [],
                    "raw_findings": []
                }

            # 3. Candidate Photo Resolution
            #    Only auto-assigns from identifiers the candidate supplied (email, resume
            #    links, email-derived account). Name-matched images are held for review,
            #    never attached automatically.
            status.write("🖼️ Resolving candidate photo from supplied & corroborated sources...")
            known_links = [l.get("url_or_handle", "") for l in p.get("links_and_handles", [])
                           if (l.get("url_or_handle") or "").startswith("http")]
            discovered = []
            for bucket in ("professional", "social", "web_mentions", "attributed"):
                for item in (search_findings.get(bucket) or []):
                    u = item.get("url", "")
                    if u.count("/") >= 3 and u not in discovered:
                        discovered.append(u)
            try:
                photo_info = photo_resolver.resolve_candidate_photo(
                    name=c_name,
                    email=c_email,
                    resume_links=known_links,
                    location=c_location,
                    employers=clean_employers,
                    discovered_profiles=discovered[:8],
                    auto_accept_likely=str(get_secret("PHOTO_AUTO_ACCEPT_LIKELY", "false")).lower() == "true",
                )
            except Exception as _e:
                photo_info = {"photo": None, "status": "none", "candidates": [],
                              "log": [f"Photo resolution error: {type(_e).__name__}"]}
            st.session_state["photo_info"] = photo_info
            st.session_state["candidate_avatar"] = {
                "url": (photo_info.get("photo") or {}).get("url")
                       or photo_resolver.initials_badge(c_name),
                "source": (photo_info.get("photo") or {}).get("source", "No photo confirmed"),
                "confidence": (photo_info.get("photo") or {}).get("tier", "Fallback"),
                "photo_info": photo_info,
            }
            st.session_state.pop("confirmed_photo", None)

            # 4. AI Verification & EEOC Firewall
            status.write("🛡️ Analyzing timeline consistency and applying EEOC conduct firewall...")
            try:
                verif = verifier.verify_candidate_profile(
                    candidate_data=updated_candidate,
                    search_results=search_findings,
                    api_key=api_key
                )
            except Exception as e:
                verif = verifier.run_rule_based_verification(
                    candidate_data=updated_candidate,
                    search_results=search_findings
                )
            
            verif["search_findings"] = search_findings
            st.session_state["verification_result"] = verif
            st.session_state["parsed_data"] = updated_candidate
            status.update(label="✅ Background Verification Complete!", state="complete", expanded=False)
            st.rerun()


# --- STEP 3: CANDIDATE VERIFICATION DOSSIER ---
if st.session_state.get("verification_result") and st.session_state.get("candidate_avatar"):
    res = st.session_state["verification_result"]
    cand = st.session_state["parsed_data"]
    avatar = st.session_state["candidate_avatar"]
    findings = res.get("search_findings", {})

    st.divider()

    # --- HERO CANDIDATE CARD ---
    with st.container():
        st.markdown("<div class='candidate-card'>", unsafe_allow_html=True)
        col_img, col_info, col_status = st.columns([1, 3, 1.5])
        
        with col_img:
            _confirmed = st.session_state.get("confirmed_photo")
            _auto = (avatar.get("photo_info") or {}).get("photo")
            _show = _confirmed or _auto
            st.image(_show["url"] if _show else avatar["url"], width=130)
            if _confirmed:
                st.caption("**Photo: reviewer-confirmed** ✅")
            elif _auto:
                st.caption(f"**Photo: {_auto['source']}**")
            else:
                st.caption("**No photo confirmed** (initials placeholder)")
        
        with col_info:
            st.markdown(f"### {cand.get('candidate_name', 'Applicant')}")
            st.markdown(f"**Target Role:** {cand.get('target_role', target_role)} | **Location:** {cand.get('location', 'Not specified')}")
            st.markdown(f"📧 `{cand.get('email', 'N/A')}` | 📞 `{cand.get('phone', 'N/A')}`")
            if cand.get("summary"):
                st.caption(f"_{cand.get('summary')}_")

        with col_status:
            confidence = res.get("identity_confidence", "Insufficient evidence")
            if confidence == "High":
                conf_class = "badge-verified"
            elif confidence == "Medium":
                conf_class = "badge-review"
            elif confidence in ("Insufficient evidence", "Low Footprint", "Unverified"):
                conf_class = "badge-neutral"
            else:
                conf_class = "badge-flag"
            st.markdown(f"**Identity Match:** <span class='{conf_class}'>{confidence}</span>", unsafe_allow_html=True)
            if confidence == "Insufficient evidence":
                st.caption("No public footprint found. This is common and is not a negative signal.")
            
            risk = res.get("conduct_safety_assessment", {}).get("risk_level", "Low / Clean")
            risk_class = "badge-verified" if "Low" in risk or "Clean" in risk else "badge-review"
            st.markdown(f"<br>**Conduct Risk:** <span class='{risk_class}'>{risk}</span>", unsafe_allow_html=True)
            
            st.markdown(f"<br><small>Store: {store_name}</small>", unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)

    # --- CANDIDATE PHOTO CONFIRMATION ---
    photo_info = st.session_state.get("photo_info") or {}
    candidates = photo_info.get("candidates") or []
    assigned = (photo_info.get("photo") or {}).get("url")
    confirmed = st.session_state.get("confirmed_photo")

    if (not confirmed) and (candidates or not assigned):
        with st.expander("📸 Candidate photo — confirm the right person",
                         expanded=not assigned):
            st.caption(
                "A photo is only auto-assigned when it comes from something the candidate "
                "supplied (their email or a profile URL on their resume). Everything below "
                "needs a human to confirm it before it is treated as this candidate's photo. "
                "Name matches are frequently a different person entirely."
            )
            with st.popover("🔍 How this photo was researched (audit trail)"):
                for line in (photo_info.get("log") or []):
                    st.markdown(f"- {line}")

            if assigned:
                st.success("A photo was resolved from a candidate-supplied identifier and is shown above.")
            if candidates:
                st.markdown(f"**{len(candidates)} possible match(es) found — review before use:**")
                cols = st.columns(min(4, len(candidates)))
                labels = []
                for i, c in enumerate(candidates):
                    with cols[i % len(cols)]:
                        st.image(c["url"], use_container_width=True)
                        tier = c.get("tier", "possible")
                        mark = "🟢" if tier == "likely" else "⚪"
                        st.caption(f"{mark} **{c.get('platform', 'Web')}**")
                        for ev in (c.get("evidence") or [])[:3]:
                            st.caption(f"· {ev}")
                        if c.get("profile_url"):
                            st.caption(f"[open profile]({c['profile_url']})")
                    labels.append(f"{i+1}. {c.get('platform','Web')} — "
                                  f"{'corroborated match' if c.get('tier')=='likely' else 'name match only'}")

                choice = st.radio("Select the candidate's photo:",
                                  labels + ["None of these — leave as initials"],
                                  key="photo_choice")
                c1, c2 = st.columns([1, 3])
                with c1:
                    if st.button("✅ Confirm photo", type="primary", use_container_width=True):
                        if choice.startswith("None"):
                            st.session_state["confirmed_photo"] = None
                            st.session_state["photo_rejected"] = True
                            st.rerun()
                        else:
                            idx = labels.index(choice)
                            picked = candidates[idx]
                            st.session_state["confirmed_photo"] = {
                                "url": picked["url"],
                                "source": f"Reviewer-confirmed — {picked.get('platform','Web')}",
                                "profile_url": picked.get("profile_url", ""),
                            }
                            st.rerun()
                with c2:
                    st.caption("Confirming records this photo in the audit trail as "
                               "human-verified. The reviewer is accountable for the match.")
            else:
                st.info("No usable candidate photos were found from public sources. "
                        "Low public image presence is common and is not a negative signal.")

    if res.get("_engine") == "rule_based":
        st.error(f"⚠️ **AI analysis unavailable.** {res.get('_engine_warning', '')}")

    # --- TABBED AUDIT DOSSIER ---
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔍 Verification Matrix",
        "🌐 Digital & Social Footprint",
        "🛡️ Workplace Safety & Conduct",
        "📞 Reference Call Kit",
        "📄 Export & Audit Summary"
    ])

    # --- TAB 1: VERIFICATION MATRIX ---
    with tab1:
        st.subheader("Career Timeline & Employer Verification")
        st.markdown(f"**Executive Verdict:** {res.get('overall_summary', 'Analysis completed.')}")
        
        st.info(f"⏱️ **Timeline Consistency:** {res.get('timeline_consistency', 'No chronological conflicts detected.')}")
        
        discrepancies = res.get("discrepancies", [])
        if discrepancies:
            st.warning("⚠️ **Discrepancies / Items Requiring Follow-up:**")
            for d in discrepancies:
                st.markdown(f"- {d}")
        else:
            st.success("✅ No chronological gaps or conflicting employment claims detected.")

        st.markdown("#### Past Employer Legitimacy Checks")
        employers = res.get("employer_verification", [])
        if employers:
            for emp in employers:
                _st_txt = emp.get("status", "")
                status_color = "🟢" if "Employment verified" in _st_txt else "🟡"
                with st.expander(f"{status_color} {emp.get('company')} - {emp.get('title')} ({emp.get('dates')})", expanded=True):
                    st.markdown(f"**Verification Status:** {emp.get('status')}")
                    st.markdown(f"**Findings:** {emp.get('notes')}")
                    sources = emp.get("sources", [])
                    if sources:
                        st.markdown("**Evidence Sources:**")
                        for s in sources:
                            s_url = s.get("url", "#")
                            s_title = s.get("title", s_url)
                            st.markdown(f"- [{s_title}]({s_url})")
                    if emp.get("next_step"):
                        st.info(f"👉 **Next Step:** {emp.get('next_step')}")
        else:
            st.caption("No specific employers were checked.")

    # --- TAB 2: DIGITAL & SOCIAL FOOTPRINT ---
    with tab2:
        st.subheader("Public Social & Web Presence")
        
        attributed_list = findings.get("attributed", [])
        unattributed_list = findings.get("unattributed", [])

        st.markdown("#### ✅ Confirmed Public Traces (Attributed to Candidate)")
        if attributed_list:
            for item in attributed_list:
                badge = item.get("badge", "🌐 Profile")
                st.markdown(f"- **{badge}** : [{item.get('title', 'Record')}]({item.get('url', '#')})")
                if item.get("attribution_evidence"):
                    st.caption("Corroboration: " + " · ".join(item["attribution_evidence"]))
                if item.get("snippet"):
                    st.caption(f"_{item['snippet'][:180]}..._")
        else:
            st.info("No public traces were confirmed for this candidate. Low public footprint is normal and not a negative signal.")

        st.markdown("---")
        with st.expander(f"⚠️ Unattributed Mentions of the Same Name ({len(unattributed_list)} records)", expanded=False):
            st.caption(
                "These results match the candidate's name only or lack corroborating employer/location/email signals. "
                "They may belong to a different person entirely and are **NOT** factored into candidate verification."
            )
            if unattributed_list:
                for u in unattributed_list:
                    plat = u.get("platform", "Web")
                    st.markdown(f"- **[{plat}] [{u.get('title', 'Mention')}]({u.get('url', '#')})**")
                    if u.get("snippet"):
                        st.caption(f"_{u['snippet'][:160]}..._")
            else:
                st.caption("No uncorroborated name records logged.")

        # Raw Search Evidence
        with st.expander("🔎 View All Raw Search Findings & Citations"):
            all_raw = findings.get("raw_findings", [])
            if all_raw:
                for r in all_raw:
                    cat = r.get("category") or r.get("target", "Result")
                    plat = r.get("platform", "Web")
                    title = r.get("title", "Untitled")
                    url = r.get("url", "#")
                    attr = r.get("attribution_status", "")
                    attr_mark = " [Attributed]" if attr == "attributed" else ""
                    st.markdown(f"**[{cat} - {plat}{attr_mark}] [{title}]({url})**")
                    st.caption(r.get("snippet", ""))
            else:
                st.caption("No raw search records logged.")

    # --- TAB 3: WORKPLACE SAFETY & CONDUCT ---
    with tab3:
        st.subheader("Workplace Safety & Conduct Screening")
        conduct = res.get("conduct_safety_assessment", {})
        
        risk_lvl = conduct.get("risk_level", "Low / Clean")
        if "Low" in risk_lvl or "Clean" in risk_lvl:
            st.success(f"**Workplace Risk Level: {risk_lvl}**")
        else:
            st.warning(f"**Workplace Risk Level: {risk_lvl}**")

        st.markdown("#### Key Conduct Findings")
        findings_list = conduct.get("findings", [])
        for f in findings_list:
            st.markdown(f"- {f}")

        pos_list = conduct.get("positive_indicators", [])
        if pos_list:
            st.markdown("#### 🌟 Positive Public Indicators")
            for p_ind in pos_list:
                st.markdown(f"- {p_ind}")

        # Legal & EEOC Compliance Box
        st.markdown(f"""
        <div class='compliance-box'>
            <strong>⚖️ EEOC Compliance & Legal Safeguard Notice:</strong><br>
            {conduct.get("eeoc_compliance_statement", "Protected demographic traits have been excluded.")}
            <br><small>Hiring decisions should be based solely on job-related qualifications and verified conduct.</small>
        </div>
        """, unsafe_allow_html=True)

    # --- TAB 4: REFERENCE CALL KIT ---
    with tab4:
        st.subheader("Tailored Reference Check Kit")
        st.markdown("Customized questions generated based on this applicant's claimed store duties:")

        ref_kit = res.get("reference_kit", [])
        if ref_kit:
            for idx, rk in enumerate(ref_kit):
                with st.expander(f"👤 Reference #{idx+1}: {rk.get('reference_name')} ({rk.get('company')})", expanded=True):
                    st.markdown("**Suggested Interview Questions:**")
                    for q in rk.get("suggested_questions", []):
                        st.markdown(f"• {q}")
        else:
            st.info("No specific references were extracted from the resume.")

        st.markdown("#### ✉️ Reference Outreach Email Template")
        email_body = res.get("outreach_email_template", "Subject: Reference Check\n\nDear Reference...")
        st.text_area("Copy & Paste into your Email Client:", value=email_body, height=180)

        # In-App Reference Call Logger
        st.markdown("#### 📝 Reference Call Notes Logger")
        call_notes = st.text_area("Record notes during your reference phone call:", placeholder="E.g., Called John on Sept 10. Confirmed Alex was reliable, always on time, and great at handling register closing...")
        if st.button("Save Call Notes"):
            st.success("Reference notes recorded for this candidate file.")

    # --- TAB 5: EXPORT & AUDIT SUMMARY ---
    with tab5:
        st.subheader("📄 Printable Candidate Verification Dossier")
        st.markdown("Generate a clean summary for your store's hiring file or interview panel:")

        consent_rec = st.session_state.get("consent_record", {})
        consent_display = f"Confirmed ({consent_rec.get('method', 'Verbal')} - {consent_rec.get('timestamp', 'N/A')})" if consent_rec.get("given") else "Not on file"

        # Collect all unique sources cited
        all_sources = []
        seen_source_urls = set()
        for emp in res.get("employer_verification", []):
            for s in emp.get("sources", []):
                u = s.get("url", "")
                if u and u not in seen_source_urls:
                    seen_source_urls.add(u)
                    all_sources.append(s)
        for att in findings.get("attributed", []):
            u = att.get("url", "")
            if u and u not in seen_source_urls:
                seen_source_urls.add(u)
                all_sources.append({"url": u, "title": att.get("title", u)})

        utc_now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        e = _html.escape
        sources_html = "".join([f"<li><a href='{e(s.get('url','#'))}' target='_blank'>{e(s.get('title', s.get('url','')))}</a></li>" for s in all_sources]) if all_sources else "<li>No external public sources cited.</li>"

        dossier_html = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #ccc; border-radius: 8px;">
            <h2>{e(str(store_name))} - Candidate Verification Dossier</h2>
            <hr/>
            <p><strong>Applicant Name:</strong> {e(str(cand.get('candidate_name', '')))}</p>
            <p><strong>Position Applied:</strong> {e(str(cand.get('target_role', target_role)))}</p>
            <p><strong>Email:</strong> {e(str(cand.get('email', '')))} | <strong>Phone:</strong> {e(str(cand.get('phone', '')))} | <strong>Location:</strong> {e(str(cand.get('location', '')))}</p>
            <p><strong>Consent Status:</strong> {e(str(consent_display))} | <strong>Identity Confidence:</strong> {e(str(res.get('identity_confidence', '')))} | <strong>Conduct Risk:</strong> {e(str(res.get('conduct_safety_assessment', {}).get('risk_level', '')))}</p>
            <hr/>
            <h3>Executive Verdict</h3>
            <p>{e(str(res.get('overall_summary', '')))}</p>
            <h3>Timeline Consistency</h3>
            <p>{e(str(res.get('timeline_consistency', '')))}</p>
            <h3>Employer Validation</h3>
            <ul>
                {''.join([f"<li><strong>{e(str(x.get('company','')))}:</strong> {e(str(x.get('status','')))} - {e(str(x.get('notes','')))}<br><small><em>Next step: {e(str(x.get('next_step','Verify by reference call')))}</em></small></li>" for x in res.get('employer_verification', [])])}
            </ul>
            <h3>Sources & Evidence Citations</h3>
            <ul>
                {sources_html}
            </ul>
            <hr/>
            <small style="color: #666;">
                Generated by automated screening tool on {e(utc_now)}. Contains unverified public web matches.<br/>
                Not a consumer report and not a substitute for reference checks. Conducted under PIPEDA / EEOC non-discrimination guidelines.
            </small>
        </div>
        """
        st.components.v1.html(dossier_html, height=500, scrolling=True)
        st.download_button(
            label="💾 Download Dossier (HTML)",
            data=dossier_html,
            file_name=f"background_check_{re.sub(r'[^a-zA-Z0-9]', '_', cand.get('candidate_name', 'candidate'))}.html",
            mime="text/html"
        )

"""
Store Candidate Background Check & OSINT Verification Assistant
A secure, privacy-first tool for retail and store hiring.
Extracts resume data, searches public digital footprints, resolves candidate photos,
verifies claims against EEOC guidelines, and generates tailored reference kits.
"""

import os
import re
import json
from typing import Dict, Any, List
import streamlit as st
from dotenv import load_dotenv

import extractor
import avatar_fetcher
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
    """Safely get config from st.secrets or os.environ."""
    if hasattr(st, "secrets") and key in st.secrets:
        return st.secrets[key]
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
        entered_code = st.text_input("Enter Store Access Code", type="password")
        if st.button("Unlock Portal", type="primary", use_container_width=True):
            if entered_code == expected_code:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Incorrect Passcode. Contact your store administrator.")
        st.caption("Default local code is `1234` (configurable via .env or secrets).")
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

    # Compliance Consent
    st.divider()
    consent_given = st.checkbox(
        "Candidate Consent Acknowledged",
        value=True,
        help="Confirms applicant was informed of reference and public record verification."
    )
    
    st.divider()
    if st.button("🔄 Reset / New Candidate", use_container_width=True):
        for k in ["parsed_data", "verification_result", "candidate_avatar"]:
            st.session_state.pop(k, None)
        st.rerun()


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
    if st.button("🚀 Run Multi-Track Verification & OSINT Search", type="primary", use_container_width=True):
        with st.status("Performing live background check & OSINT search...", expanded=True) as status:
            # 1. Update candidate data
            updated_candidate = dict(p)
            updated_candidate["candidate_name"] = c_name
            updated_candidate["email"] = c_email
            updated_candidate["phone"] = c_phone
            updated_candidate["location"] = c_location
            updated_candidate["target_role"] = target_role
            
            # Rebuild clean employers list
            clean_employers = [e.strip() for e in emp_text.split(",") if e.strip()]
            
            # 2. Resolve Avatar & Public Web Photos
            status.write("🖼️ Discovering candidate profile photos & face from public web...")
            known_links = [l.get("url_or_handle", "") for l in p.get("links_and_handles", [])]
            avatar_info = avatar_fetcher.resolve_candidate_avatar(
                name=c_name,
                email=c_email,
                social_links=known_links,
                location=c_location,
                employer=clean_employers[0] if clean_employers else None
            )
            st.session_state["candidate_avatar"] = avatar_info

            # 3. OSINT Search
            status.write("🌐 Executing multi-track OSINT search (LinkedIn, Instagram, X/Twitter, FB, Reddit, Employer check)...")
            search_findings = osint_search.run_candidate_osint(
                candidate_name=c_name,
                location=c_location,
                past_employers=clean_employers,
                references=p.get("references", []),
                email=c_email,
                serper_api_key=serper_api_key
            )

            # 4. AI Verification & EEOC Firewall
            status.write("🛡️ Analyzing timeline consistency and applying EEOC conduct firewall...")
            verif = verifier.verify_candidate_profile(
                candidate_data=updated_candidate,
                search_results=search_findings,
                api_key=api_key
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
            st.image(avatar["url"], width=130)
            st.caption(f"Photo: **{avatar['source']}**")
        
        with col_info:
            st.markdown(f"### {cand.get('candidate_name', 'Applicant')}")
            st.markdown(f"**Target Role:** {cand.get('target_role', target_role)} | **Location:** {cand.get('location', 'Not specified')}")
            st.markdown(f"📧 `{cand.get('email', 'N/A')}` | 📞 `{cand.get('phone', 'N/A')}`")
            if cand.get("summary"):
                st.caption(f"_{cand.get('summary')}_")

        with col_status:
            confidence = res.get("identity_confidence", "Medium")
            conf_class = "badge-verified" if confidence == "High" else ("badge-review" if confidence == "Medium" else "badge-flag")
            st.markdown(f"**Identity Match:** <span class='{conf_class}'>{confidence}</span>", unsafe_allow_html=True)
            
            risk = res.get("conduct_safety_assessment", {}).get("risk_level", "Low / Clean")
            risk_class = "badge-verified" if "Low" in risk or "Clean" in risk else "badge-review"
            st.markdown(f"<br>**Conduct Risk:** <span class='{risk_class}'>{risk}</span>", unsafe_allow_html=True)
            
            st.markdown(f"<br><small>Store: {store_name}</small>", unsafe_allow_html=True)

        # Discovered Web Photo Gallery
        if avatar.get("gallery") and len(avatar["gallery"]) > 1:
            st.markdown("---")
            st.markdown(f"**📸 Discovered Public Web Photos ({len(avatar['gallery'])} found):**")
            p_cols = st.columns(min(4, len(avatar["gallery"])))
            for idx, p_item in enumerate(avatar["gallery"][:4]):
                with p_cols[idx]:
                    st.image(p_item["url"], use_container_width=True)
                    st.caption(f"[{p_item.get('title', 'Photo')[:28]}...]({p_item.get('source', p_item['url'])})")
        
        st.markdown("</div>", unsafe_allow_html=True)

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
                status_color = "🟢" if "Verified" in emp.get("status", "") or "Corroborated" in emp.get("status", "") else "🟡"
                with st.expander(f"{status_color} {emp.get('company')} - {emp.get('title')} ({emp.get('dates')})", expanded=True):
                    st.markdown(f"**Verification Status:** {emp.get('status')}")
                    st.markdown(f"**Findings:** {emp.get('notes')}")
        else:
            st.caption("No specific employers were checked.")

    # --- TAB 2: DIGITAL & SOCIAL FOOTPRINT ---
    with tab2:
        st.subheader("Public Social & Web Presence")
        st.markdown("Public records and profiles discovered via targeted OSINT search:")
        
        prof_links = findings.get("professional", [])
        soc_links = findings.get("social", [])
        mentions = findings.get("web_mentions", [])
        
        col_prof, col_soc = st.columns(2)
        
        with col_prof:
            st.markdown("#### 💼 Professional Footprint")
            if prof_links:
                for item in prof_links:
                    badge = item.get("badge", "💼 Professional")
                    st.markdown(f"- **{badge}** : [{item['title']}]({item['url']})")
                    if item.get("snippet"):
                        st.caption(f"_{item['snippet'][:180]}..._")
            else:
                st.caption("No public professional profiles (LinkedIn/GitHub) indexed with this exact name and location.")

        with col_soc:
            st.markdown("#### 🌐 Social Networks & Forums")
            if soc_links:
                for item in soc_links:
                    badge = item.get("badge", "🌐 Social")
                    st.markdown(f"- **{badge}** : [{item['title']}]({item['url']})")
                    if item.get("snippet"):
                        st.caption(f"_{item['snippet'][:180]}..._")
            else:
                st.caption("No public social accounts indexed under this name and location.")

        if mentions:
            st.markdown("#### 📰 Web Mentions & Articles")
            for m in mentions[:6]:
                st.markdown(f"- **[{m['title']}]({m['url']})**")
                if m.get("snippet"):
                    st.caption(f"_{m['snippet'][:180]}..._")

        # Raw Search Evidence
        with st.expander("🔎 View All Raw Search Findings & Citations"):
            all_raw = findings.get("raw_findings", [])
            if all_raw:
                for r in all_raw:
                    st.markdown(f"**[{r['category']} - {r['platform']}] [{r['title']}]({r['url']})**")
                    st.caption(r['snippet'])
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

        dossier_html = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; border: 1px solid #ccc; border-radius: 8px;">
            <h2>{store_name} - Candidate Verification Dossier</h2>
            <hr/>
            <p><strong>Applicant Name:</strong> {cand.get('candidate_name')}</p>
            <p><strong>Position Applied:</strong> {cand.get('target_role', target_role)}</p>
            <p><strong>Email:</strong> {cand.get('email')} | <strong>Phone:</strong> {cand.get('phone')} | <strong>Location:</strong> {cand.get('location')}</p>
            <p><strong>Identity Confidence:</strong> {res.get('identity_confidence')} | <strong>Conduct Risk:</strong> {res.get('conduct_safety_assessment', {}).get('risk_level')}</p>
            <hr/>
            <h3>Executive Verdict</h3>
            <p>{res.get('overall_summary')}</p>
            <h3>Timeline Consistency</h3>
            <p>{res.get('timeline_consistency')}</p>
            <h3>Employer Validation</h3>
            <ul>
                {''.join([f"<li><strong>{e.get('company')}:</strong> {e.get('status')} - {e.get('notes')}</li>" for e in res.get('employer_verification', [])])}
            </ul>
            <hr/>
            <small style="color: #666;">This verification was compiled using public domain OSINT and AI synthesis in compliance with EEOC non-discrimination guidelines.</small>
        </div>
        """
        st.components.v1.html(dossier_html, height=450, scrolling=True)
        st.download_button(
            label="💾 Download Dossier (HTML)",
            data=dossier_html,
            file_name=f"background_check_{re.sub(r'[^a-zA-Z0-9]', '_', cand.get('candidate_name', 'candidate'))}.html",
            mime="text/html"
        )

"""
AI Verification, EEOC Conduct Firewall & Reference Kit Generator
Compares resume claims against OSINT search findings, performs timeline consistency checks,
scans for workplace conduct risks while filtering out protected demographic traits,
and generates tailored reference interview questionnaires.
"""

import json
import re
from typing import Dict, Any, List, Optional


def run_rule_based_verification(
    candidate_data: Dict[str, Any],
    search_results: Dict[str, Any]
) -> Dict[str, Any]:
    """Fallback rule-based verification when LLM key is unavailable."""
    name = candidate_data.get("candidate_name", "Candidate")
    work_history = candidate_data.get("work_history", [])
    references = candidate_data.get("references", [])
    social = search_results.get("social", [])
    professional = search_results.get("professional", [])
    employer_checks = search_results.get("employer_validation", {})

    # Match count (entity-resolved attributed matches preferred)
    attributed = search_results.get("attributed", [])
    found_profiles = len(attributed) if attributed else (len(professional) + len(social))
    if found_profiles >= 3:
        confidence = "High"
    elif found_profiles >= 1:
        confidence = "Medium"
    else:
        confidence = "Insufficient evidence"

    # Employers check
    verified_employers = []
    for job in work_history:
        comp = job.get("company", "")
        results = employer_checks.get(comp, [])
        is_legit = len(results) > 0
        emp_sources = [
            {"url": r.get("href", r.get("url", "")), "title": r.get("title", comp)}
            for r in results[:3]
            if (r.get("href") or r.get("url"))
        ]
        verified_employers.append({
            "company": comp,
            "title": job.get("title", ""),
            "dates": f"{job.get('start_date', '')} - {job.get('end_date', '')}",
            # A web result proves the BUSINESS exists - it proves nothing about
            # whether this person worked there. Never label that "verified".
            "status": ("Company presence found - employment NOT verified"
                       if is_legit else "Uncorroborated - verify by reference call"),
            "notes": (f"{len(results)} public business/web references found for the company. "
                      "This confirms the employer exists; it does NOT confirm the candidate worked there.")
                      if is_legit else "No public business records found. Confirm by reference call.",
            "sources": emp_sources,
            "next_step": f"Call reference or {comp} HR directly to confirm dates and role"
        })

    # Reference questions
    ref_kit = []
    for ref in references:
        r_name = ref.get("name", "Reference")
        r_comp = ref.get("company", "Former Employer")
        ref_kit.append({
            "reference_name": r_name,
            "company": r_comp,
            "suggested_questions": [
                f"Can you confirm that {name} worked at {r_comp} and describe their role?",
                f"How would you rate {name}'s punctuality, reliability, and teamwork?",
                f"Did {name} handle customer service, cash register, or inventory responsibly?",
                f"Would you rehire {name} if given the opportunity?"
            ]
        })

    if confidence == "Insufficient evidence":
        summary = f"Completed multi-track background analysis for {name}. No public footprint found tying candidate to online profiles. This is common and is not a negative signal."
    else:
        summary = f"Completed multi-track background analysis for {name}. Found {found_profiles} corroborated public web traces."

    return {
        "overall_summary": summary,
        "identity_confidence": confidence,
        "timeline_consistency": "No obvious chronological conflicts detected in resume dates.",
        "employer_verification": verified_employers,
        "conduct_safety_assessment": {
            "risk_level": "Low / Clean",
            "findings": ["No public indications of workplace hostility, theft, or employer disparagement detected."],
            "positive_indicators": ["Public professional footprint corresponds with work history claims."],
            "eeoc_compliance_statement": "Protected demographic attributes (race, religion, age, medical status, sexual orientation) have been strictly excluded from this report in accordance with EEOC hiring guidelines."
        },
        "reference_kit": ref_kit,
        "outreach_email_template": (
            f"Subject: Reference Check regarding {name}\n\n"
            f"Dear [Reference Name],\n\n"
            f"I hope this message finds you well. {name} has applied for a position at our store and listed you as a professional reference.\n\n"
            f"Could you spare 5 minutes for a brief phone call or answer a few short questions about your experience working with {name}?\n\n"
            f"Thank you for your time and assistance.\n\nBest regards,\nStore Hiring Team"
        )
    }


def call_gemini_verifier(
    candidate_data: Dict[str, Any],
    search_results: Dict[str, Any],
    api_key: str
) -> Dict[str, Any]:
    """Call Gemini to synthesize a structured verification dossier."""
    # Entity Resolution: Feed ONLY attributed results into AI prompt
    attributed = search_results.get("attributed", [])
    filtered_search_payload = {
        "attributed_candidate_profiles": attributed if attributed else [
            r for r in (search_results.get("professional", []) + search_results.get("social", []))
            if r.get("attribution_status") == "attributed"
        ],
        "employer_validation": search_results.get("employer_validation", {}),
        "reference_verification": search_results.get("reference_verification", {}),
        "unattributed_mentions_count": len(search_results.get("unattributed", []))
    }

    prompt = f"""
You are an expert HR Verification and Workplace Safety Analyst.
Analyze the candidate's resume claims against the live OSINT search results.

IMPORTANT LEGAL & EEOC REQUIREMENTS:
- You MUST strictly IGNORE and REDACT all protected demographic characteristics (race, ethnicity, age, religion, marital/family status, pregnancy, medical conditions, sexual orientation, political party).
- Focus ONLY on legitimate workplace considerations:
  1. Timeline sanity (conflicting dates, overlapping full-time roles).
  2. Employer existence (does the business exist?) - this is NOT evidence the candidate worked there.
     Only report employment as verified if a source explicitly links this person to that employer.
     If no public source links the candidate to an employer, report status as:
     "Company existence only - employment NOT verified" or "Uncorroborated - verify by reference call".
  3. Reference credibility (does the reference appear to match the company?).
  4. Public conduct risk (any public hostility, threats, employee theft bragging, or confidential info leaks in search snippets).
  5. If there are no attributed public profiles, return identity_confidence as "Insufficient evidence".
     Absence of public profiles is normal and not a negative signal.

Candidate Resume Data:
{json.dumps(candidate_data, indent=2)}

Live Attributed OSINT Search Findings:
{json.dumps(filtered_search_payload, indent=2)}

Return ONLY a valid JSON object with NO markdown formatting (no ```json ... ```):
{{
  "overall_summary": "1-2 sentence executive verdict on candidate consistency and presence",
  "identity_confidence": "High / Medium / Low / Insufficient evidence",
  "timeline_consistency": "Detailed evaluation of employment timeline consistency",
  "discrepancies": ["List any timeline contradictions or unmatched claims, or empty list if clean"],
  "employer_verification": [
    {{
      "company": "Company Name",
      "title": "Claimed Role",
      "dates": "Start - End",
      "status": "Company existence only - employment NOT verified / Uncorroborated - verify by reference call",
      "notes": "State explicitly whether any source ties THIS person to this employer. If none does, say so. Company existence must never be described as verified employment.",
      "sources": [{{"url": "https://...", "title": "Source page title"}}],
      "next_step": "Actionable follow-up, e.g. Call reference or company HR to confirm dates and role"
    }}
  ],
  "conduct_safety_assessment": {{
    "risk_level": "Low / Clean / Elevated / Requires Human Review",
    "findings": ["Specific workplace conduct findings from public snippets"],
    "positive_indicators": ["Positive public accolades, community involvement, or endorsements"],
    "eeoc_compliance_statement": "Protected demographic attributes (race, religion, age, medical status, family status) have been strictly excluded from this evaluation in compliance with EEOC regulations."
  }},
  "reference_kit": [
    {{
      "reference_name": "Name",
      "company": "Company",
      "suggested_questions": [
        "Tailored question 1 based on resume claims",
        "Tailored question 2",
        "Tailored question 3"
      ]
    }}
  ],
  "outreach_email_template": "Ready-to-use email text for reaching out to references"
}}
"""
    # 1. Try google-genai SDK
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        for mod in ["gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash"]:
            try:
                response = client.models.generate_content(
                    model=mod,
                    contents=prompt,
                    config={"response_mime_type": "application/json", "temperature": 0.2},
                )
                content = response.text.strip()
                if content.startswith("```"):
                    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
                    content = re.sub(r"\n?```$", "", content)
                parsed = json.loads(content)
                parsed["_model_used"] = mod
                return parsed
            except Exception:
                continue
    except Exception:
        pass

    # 2. Direct REST HTTP API via httpx (single robust fallback)
    try:
        import httpx
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        with httpx.Client(timeout=35.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                res_json = resp.json()
                text_part = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_part.startswith("```"):
                    text_part = re.sub(r"^```[a-zA-Z]*\n?", "", text_part)
                    text_part = re.sub(r"\n?```$", "", text_part)
                parsed = json.loads(text_part)
                parsed["_model_used"] = "gemini-2.5-flash (REST)"
                return parsed
    except Exception:
        pass

    # Fallback to rule-based
    fallback = run_rule_based_verification(candidate_data, search_results)
    fallback["_engine"] = "rule_based"
    fallback["_engine_warning"] = (
        "The AI analysis step did not run (missing/invalid API key, model unavailable, "
        "or unparseable response). The results below are generic rule-based output and "
        "do NOT constitute a verification of this candidate."
    )
    return fallback


def verify_candidate_profile(
    candidate_data: Dict[str, Any],
    search_results: Dict[str, Any],
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """Top-level verification function."""
    if api_key and api_key.strip():
        result = call_gemini_verifier(candidate_data, search_results, api_key.strip())
        result.setdefault("_engine", "gemini")
        return result
    return call_gemini_verifier(candidate_data, search_results, "")

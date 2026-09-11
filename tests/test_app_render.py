"""
Regression test suite for Candidate Background Check Streamlit App.
Covers render pipeline, raw findings data shapes, employer evidence ledger,
entity resolution gating, and photo attribution safety.
"""

import sys
import os
import pytest
from streamlit.testing.v1 import AppTest

# Ensure repo root is on import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from osint_search import attribute_result
import photo_resolver


@pytest.fixture
def sample_candidate():
    return {
        "candidate_name": "Alex Turner",
        "email": "alex.turner.test@example.com",
        "phone": "555-0199",
        "location": "Kitchener, Ontario",
        "target_role": "Store Associate / Cashier",
        "summary": "Experienced retail customer service associate.",
        "work_history": [
            {
                "company": "Target",
                "title": "Store Associate",
                "start_date": "2021",
                "end_date": "Present",
                "location": "Kitchener, ON"
            }
        ],
        "references": [
            {
                "name": "Sarah Miller",
                "company": "Target",
                "phone": "555-999-0000",
                "email": "sarah.m@target.test"
            }
        ],
        "links_and_handles": []
    }


@pytest.fixture
def sample_verification_result():
    return {
        "overall_summary": "Candidate profile demonstrates timeline consistency and legitimate previous retail presence.",
        "identity_confidence": "Medium",
        "timeline_consistency": "Dates are chronologically valid with no overlapping conflicts.",
        "discrepancies": [],
        "employer_verification": [
            {
                "company": "Target",
                "title": "Store Associate",
                "dates": "2021 - Present",
                "status": "Company presence found - employment NOT verified",
                "notes": "Target business presence confirmed. Employment records require reference confirmation.",
                "sources": [{"url": "https://www.target.com", "title": "Target Official Store"}],
                "next_step": "Call reference or Target HR to confirm employment claims."
            }
        ],
        "conduct_safety_assessment": {
            "risk_level": "Low / Clean",
            "findings": ["No hostile public conduct detected."],
            "positive_indicators": ["Verified active store employment footprint."],
            "eeoc_compliance_statement": "Protected demographic attributes excluded in compliance with EEOC standards."
        },
        "reference_kit": [
            {
                "reference_name": "Sarah Miller",
                "company": "Target",
                "suggested_questions": [
                    "Can you confirm Alex's role at Target?",
                    "How was Alex's punctuality and cash-handling accuracy?"
                ]
            }
        ],
        "outreach_email_template": "Subject: Reference Check regarding Alex Turner\n\nDear Sarah...",
        "search_findings": {
            "professional": [],
            "social": [],
            "web_mentions": [],
            "attributed": [
                {
                    "platform": "LinkedIn",
                    "title": "Alex Turner - Store Associate at Target Kitchener",
                    "url": "https://linkedin.com/in/alex-turner-target-kitchener",
                    "snippet": "Store Associate at Target Kitchener Ontario",
                    "attribution_status": "attributed",
                    "attribution_evidence": ["Full name matched", "Employer Target matched", "Kitchener matched"]
                }
            ],
            "unattributed": [
                {
                    "platform": "Web",
                    "title": "Alex Turner - Musician and Vocalist",
                    "url": "https://en.wikipedia.org/wiki/Alex_Turner",
                    "snippet": "English musician, singer, and songwriter",
                    "attribution_status": "unattributed"
                }
            ],
            "raw_findings": [
                {
                    "target": "LinkedIn",
                    "category": "Professional",
                    "platform": "LinkedIn",
                    "title": "Alex Turner - Store Associate at Target Kitchener",
                    "url": "https://linkedin.com/in/alex-turner-target-kitchener",
                    "snippet": "Store Associate at Target Kitchener Ontario",
                    "attribution_status": "attributed"
                },
                {
                    "target": "Public News",
                    "category": "News",
                    "platform": "Web",
                    "title": "Alex Turner - Musician and Vocalist",
                    "url": "https://en.wikipedia.org/wiki/Alex_Turner",
                    "snippet": "English musician, singer, and songwriter",
                    "attribution_status": "unattributed"
                }
            ],
            "employer_validation": {
                "Target": [{"title": "Target Stores", "url": "https://target.com"}]
            },
            "reference_verification": {}
        }
    }


def test_no_exception_on_full_run(sample_candidate, sample_verification_result):
    """App must render a complete dossier without raising any exceptions."""
    at = AppTest.from_file("app.py", default_timeout=120)
    at.session_state["authenticated"] = True
    at.session_state["parsed_data"] = sample_candidate
    at.session_state["photo_info"] = {"photo": None, "candidates": [], "log": ["Initials placeholder badge"]}
    at.session_state["candidate_avatar"] = {
        "url": "https://ui-avatars.com/api/?name=Alex+Turner",
        "source": "Initials placeholder",
        "confidence": "Fallback"
    }
    at.session_state["verification_result"] = sample_verification_result
    at.session_state["consent_record"] = {
        "given": True,
        "method": "Written Application",
        "timestamp": "2026-09-11 12:00:00 UTC"
    }
    at.run()
    assert not at.exception, f"App raised an exception: {at.exception}"


def test_raw_findings_shape(sample_verification_result):
    """Every record in raw_findings must contain category, platform, title, url, snippet."""
    findings = sample_verification_result["search_findings"]
    raw = findings.get("raw_findings", [])
    assert len(raw) > 0, "raw_findings must not be empty in test fixture"
    required_keys = {"category", "platform", "title", "url", "snippet"}
    for idx, r in enumerate(raw):
        missing = required_keys - set(r.keys())
        assert not missing, f"raw_findings item {idx} missing keys: {missing}"


def test_no_verified_label_without_source(sample_verification_result):
    """No employer status claiming 'Employment verified' may render without sources."""
    employers = sample_verification_result.get("employer_verification", [])
    for emp in employers:
        status = emp.get("status", "")
        sources = emp.get("sources", [])
        if "Employment verified" in status or "Verified" in status:
            assert sources and len(sources) > 0, (
                f"Employer '{emp.get('company')}' claimed '{status}' without non-empty sources list."
            )


def test_name_match_alone_is_not_attributed():
    """attribute_result() must reject strangers, surname-only matches, and aggregator pages."""
    candidate_name = "Marcus Delaney"
    loc = "Kitchener, Ontario"
    employers = ["Tim Hortons"]
    email = "marcus.delaney@example.com"

    # Case 1: Surname only ('Delaney' alone)
    r1 = {
        "title": "John Delaney - Senior Financial Executive",
        "snippet": "John Delaney is an executive working in Toronto",
        "url": "https://example.com/john-delaney"
    }
    status1, ev1 = attribute_result(r1, candidate_name, loc, employers, email)
    assert status1 == "unattributed", f"Expected unattributed for surname-only, got {status1}: {ev1}"

    # Case 2: Full name matched but NO supporting location/employer/email signal
    r2 = {
        "title": "Marcus Delaney - Professional Musician",
        "snippet": "Marcus Delaney plays guitar in Seattle Washington",
        "url": "https://example.com/marcus-delaney-music"
    }
    status2, ev2 = attribute_result(r2, candidate_name, loc, employers, email)
    assert status2 == "unattributed", f"Expected unattributed for stranger with same name, got {status2}: {ev2}"

    # Case 3: Aggregator / Directory page (e.g. LinkedIn /pub/dir/)
    r3 = {
        "title": "Marcus Delaney Profiles - LinkedIn Directory",
        "snippet": "View profiles of 40+ people named Marcus Delaney in Kitchener",
        "url": "https://www.linkedin.com/pub/dir/Marcus/Delaney"
    }
    status3, ev3 = attribute_result(r3, candidate_name, loc, employers, email)
    assert status3 == "unattributed", f"Expected unattributed for aggregator URL, got {status3}: {ev3}"

    # Case 4: Full name matched AND location/employer signal present
    r4 = {
        "title": "Marcus Delaney - Shift Supervisor at Tim Hortons Kitchener",
        "snippet": "Marcus Delaney works in Kitchener Ontario at Tim Hortons",
        "url": "https://www.linkedin.com/in/marcus-delaney-kw"
    }
    status4, ev4 = attribute_result(r4, candidate_name, loc, employers, email)
    assert status4 == "attributed", f"Expected attributed when name + employer + city match, got {status4}: {ev4}"
    assert len(ev4) >= 2


def test_photo_never_auto_assigns_name_match():
    """resolve_candidate_photo with no candidate-supplied identifiers must return photo=None."""
    res = photo_resolver.resolve_candidate_photo(
        name="Marcus Delaney",
        email="marcus.unregistered.candidate@example.com",
        location="Kitchener, Ontario",
        employers=["Tim Hortons"],
        auto_accept_likely=False
    )
    assert res["photo"] is None, "A name-matched candidate photo was auto-assigned without confirmation!"
    assert res["status"] in ("possible", "none"), f"Unexpected status: {res['status']}"
    for c in res.get("candidates", []):
        if c.get("tier") != "likely":
            assert c.get("tier") == "possible", f"Uncorroborated candidate had unexpected tier: {c.get('tier')}"

"""
Unit and integration test script for Candidate Background Check modules.
Tests avatar fetching, OSINT search, extractor fallback, and verifier logic.
"""

import sys
import unittest
from avatar_fetcher import resolve_candidate_avatar, get_initials_avatar, check_gravatar
from osint_search import derive_handles_from_email, run_candidate_osint
from extractor import heuristic_parse_resume
from verifier import run_rule_based_verification


class TestBackgroundCheckModules(unittest.TestCase):

    def test_avatar_resolver(self):
        # Test fallback initials
        res = resolve_candidate_avatar("Jane Doe", email="unknown_user_99999_xyz@nonexistentdomain.com")
        self.assertIn("url", res)
        self.assertTrue(res["url"].startswith("http"))
        self.assertEqual(res["confidence"], "Fallback")

        # Test GitHub avatar resolution
        res_gh = resolve_candidate_avatar("Torvalds", github_handle="torvalds")
        self.assertIn("github.com/torvalds.png", res_gh["url"])
        self.assertEqual(res_gh["confidence"], "High")

    def test_handle_derivation(self):
        handles = derive_handles_from_email("john.doe99@example.com")
        self.assertIn("john.doe99", handles)
        self.assertIn("johndoe99", handles)

    def test_heuristic_parser(self):
        sample_resume = """
        Alex Turner
        alex.turner@example.com
        (555) 321-4567
        Austin, TX

        EXPERIENCE
        Store Associate at Target
        June 2021 - Present
        - Managed cash register and inventory stocking
        - Provided customer support

        Cashier at Best Buy
        Jan 2019 - May 2021
        - Handled customer transactions and returns
        """
        parsed = heuristic_parse_resume(sample_resume)
        self.assertEqual(parsed["candidate_name"], "Alex Turner")
        self.assertEqual(parsed["email"], "alex.turner@example.com")
        self.assertIn("555", parsed["phone"])

    def test_verifier_rule_based(self):
        candidate_data = {
            "candidate_name": "Alex Turner",
            "work_history": [
                {"company": "Target", "title": "Store Associate", "start_date": "2021", "end_date": "Present"}
            ],
            "references": [
                {"name": "Sarah Miller", "company": "Target", "phone": "555-999-0000"}
            ]
        }
        search_results = {
            "professional": [{"platform": "LinkedIn", "title": "Alex Turner - Retail", "url": "https://linkedin.com", "snippet": "Target store associate"}],
            "social": [],
            "employer_validation": {"Target": [{"title": "Target Stores", "url": "https://target.com"}]},
            "reference_verification": {}
        }
        report = run_rule_based_verification(candidate_data, search_results)
        self.assertIn("overall_summary", report)
        self.assertEqual(report["identity_confidence"], "Medium")
        self.assertIn("eeoc_compliance_statement", report["conduct_safety_assessment"])
        self.assertTrue(len(report["reference_kit"]) > 0)
        self.assertIn("Sarah Miller", report["reference_kit"][0]["reference_name"])


if __name__ == "__main__":
    print("Running background check system test suite...")
    unittest.main()

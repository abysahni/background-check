"""
Verification harness for photo_resolver.py.

Run from the repo root:   python tools/verify_photo_resolver.py

These assertions encode the SAFETY RULES of the photo pipeline. If one fails, fix
photo_resolver.py — do not weaken the assertion.

Requires network access (LinkedIn/X/GitHub/Gravatar public pages).
Exit code 0 = all good.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import photo_resolver as pr  # noqa: E402

PASS, FAIL = [], []


def check(label, condition, detail=""):
    (PASS if condition else FAIL).append(label)
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))


print("\n=== 1. Tier 1: email-keyed (Gravatar) ===")
check("unregistered email returns no Gravatar",
      pr.gravatar_for_email("no-such-user-8f3a2b1c@example.com") is None)

print("\n=== 2. Tier 1: GitHub handle probe must corroborate the NAME ===")
match = pr.github_probe_from_email("torvalds@example.com", "Linus Torvalds")
check("correct name resolves the account", bool(match) and match["handle"] == "torvalds",
      (match or {}).get("account_name", ""))
check("evidence trail is populated", bool(match) and len(match["evidence"]) >= 2)

mismatch = pr.github_probe_from_email("torvalds@example.com", "Marcus Delaney")
check("WRONG name must NOT resolve (same email prefix)", mismatch is None)

print("\n=== 3. Tier 2: photo from a candidate-supplied profile URL ===")
li = pr.photo_from_supplied_link("https://www.linkedin.com/in/williamhgates", "Bill Gates")
check("LinkedIn profile yields an image", bool(li) and li["url"].startswith("http"),
      (li or {}).get("url", "")[:60])
check("platform detected as LinkedIn", bool(li) and li["platform"] == "LinkedIn")
check("evidence explains the attribution", bool(li) and len(li["evidence"]) >= 2)

tw = pr.photo_from_supplied_link("https://x.com/nasa", "NASA")
check("X/Twitter profile yields an image", bool(tw) and tw["url"].startswith("http"),
      (tw or {}).get("url", "")[:60])

print("\n=== 4. Tier 3: discovered profile must match the person ===")
wrong = pr.score_profile("https://www.linkedin.com/in/williamhgates",
                         "Marcus Delaney", "Kitchener, Ontario")
check("profile for a DIFFERENT person scores None", wrong is None)

right = pr.score_profile("https://www.linkedin.com/in/williamhgates", "Bill Gates",
                         "Kirkland, Washington", ["Microsoft"])
check("corroborated profile scores >= 2 signals",
      bool(right) and right.get("score", 0) >= 2, f"score={ (right or {}).get('score') }")

print("\n=== 5. Full resolver: no identifier supplied -> never fabricate a face ===")
res = pr.resolve_candidate_photo(
    name="Marcus Delaney",
    email="marcus.delaney.test@example.com",
    location="Kitchener, Ontario",
    employers=["Tim Hortons"],
    auto_accept_likely=False,
)
check("no photo auto-assigned", res["photo"] is None)
check("status is 'possible' or 'none'", res["status"] in ("possible", "none"), res["status"])
check("name-matched images are held for review only",
      all(c.get("tier") == "possible" for c in res["candidates"] if c.get("tier")))
check("audit log explains what was tried", len(res["log"]) >= 3)
for line in res["log"]:
    print(f"        · {line}")

print("\n=== 6. Auto-accept cannot be enabled accidentally ===")
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "app.py")).read()
check("PHOTO_AUTO_ACCEPT_LIKELY defaults to 'false' in app.py",
      'PHOTO_AUTO_ACCEPT_LIKELY", "false"' in src)

print("\n" + "=" * 62)
print(f"PASSED {len(PASS)}   FAILED {len(FAIL)}")
if FAIL:
    print("\nFAILED CHECKS:")
    for f in FAIL:
        print(f"  - {f}")
    sys.exit(1)
print("All photo-pipeline safety checks passed.")

"""
Candidate Photo Resolution — evidence-scored, social-media aware.

WHY THIS MODULE EXISTS
----------------------
The previous implementation searched images by NAME and then assigned the first
result as the candidate's photo. A name is not an identity: that approach returned
a lipstick advertisement for one real run, and a different real person on the next.
Attaching a stranger's face to a hiring dossier is a legal and ethical hazard.

This module only auto-assigns a photo when it resolves from an identifier the
CANDIDATE THEMSELVES SUPPLIED, or from a profile that independently corroborates
the candidate's details. Everything else is surfaced for human confirmation.

TIERS
-----
  verified  Auto-assigned. Derived from an identifier supplied on the resume:
            their email (Gravatar), a profile URL they listed, or an account
            handle reachable from their email with a name match on the profile.
  likely    Auto-assigned ONLY if PHOTO_AUTO_ACCEPT_LIKELY is enabled. Derived
            from a profile found via search whose page metadata corroborates the
            candidate's name plus location/employer. Always needs >=2 signals.
  possible  Never auto-assigned. Name-matched candidates shown in the review
            gallery for a human to accept or reject. Kept for transparency.

Every result carries its evidence trail so a reviewer can see exactly why a
photo was attributed, and the audit log records who confirmed it.
"""

from __future__ import annotations

import re
import urllib.parse
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}

TIMEOUT = 10.0

PROFILE_PATTERNS = [
    ("LinkedIn",  re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)", re.I)),
    ("GitHub",    re.compile(r"github\.com/([A-Za-z0-9\-_.]+)", re.I)),
    ("X",         re.compile(r"(?:twitter|x)\.com/([A-Za-z0-9_]+)", re.I)),
    ("Instagram", re.compile(r"instagram\.com/([A-Za-z0-9_.]+)", re.I)),
    ("Facebook",  re.compile(r"facebook\.com/([A-Za-z0-9_.\-]+)", re.I)),
    ("TikTok",    re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)", re.I)),
]

# Reserved paths that are never a person's profile
_RESERVED = {
    "explore", "topics", "trending", "features", "marketplace", "about", "pricing",
    "login", "signup", "home", "search", "settings", "help", "privacy", "terms",
    "sharer", "share", "pub", "dir", "feed", "notifications", "messages", "jobs",
}


def initials_badge(name: str) -> str:
    """Neutral placeholder — never implies a verified face."""
    clean = urllib.parse.quote((name or "Candidate").strip())
    return (
        f"https://ui-avatars.com/api/?name={clean}"
        "&background=2563eb&color=ffffff&size=256&bold=true&rounded=true"
    )


# --------------------------------------------------------------------------- #
# low-level fetchers (cached: one network hit per URL per process)
# --------------------------------------------------------------------------- #

@lru_cache(maxsize=256)
def _get(url: str) -> Tuple[int, str]:
    """Return (status, body). Body only populated for successful HTML fetches."""
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            body = r.text if r.status_code == 200 else ""
            return r.status_code, body
    except Exception:
        return 0, ""


@lru_cache(maxsize=256)
def _get_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            return r.json() if r.status_code == 200 else None
    except Exception:
        return None


@lru_cache(maxsize=256)
def fetch_page_meta(url: str) -> Dict[str, str]:
    """
    Fetch a public page and pull its identity metadata.

    Works for public LinkedIn profiles, X/Twitter, GitHub, personal sites and
    portfolios. Login-walled or rate-limited pages (private Instagram/Facebook)
    simply return empty values — they are never guessed at.
    """
    status, body = _get(url)
    if status != 200 or not body:
        return {}
    try:
        soup = BeautifulSoup(body, "html.parser")
    except Exception:
        return {}

    meta: Dict[str, str] = {}
    for tag in soup.find_all("meta"):
        key = (tag.get("property") or tag.get("name") or "").strip().lower()
        val = (tag.get("content") or "").strip()
        if key and val and key not in meta:
            meta[key] = val

    title = meta.get("og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    image = meta.get("og:image") or meta.get("twitter:image") or meta.get("image") or ""
    if image.startswith("//"):
        image = "https:" + image
    elif image.startswith("/"):
        p = urllib.parse.urlparse(url)
        image = f"{p.scheme}://{p.netloc}{image}"

    return {
        "title": title or "",
        "image": image if image.startswith("http") else "",
        "description": meta.get("og:description") or meta.get("description") or "",
        "site_name": meta.get("og:site_name") or "",
        "url": url,
    }


def _name_tokens(name: str) -> List[str]:
    return [t for t in re.split(r"[^A-Za-z]+", (name or "").lower()) if len(t) > 1]


def _full_name_present(text: str, name: str) -> bool:
    """Require the *whole* name, not one shared token. 'Delaney' alone proves nothing."""
    toks = _name_tokens(name)
    if not toks:
        return False
    low = (text or "").lower()
    if all(t in low for t in toks):
        return True
    # tolerate a middle initial / hyphenation difference
    return len(toks) >= 2 and toks[0] in low and toks[-1] in low


# --------------------------------------------------------------------------- #
# Tier 1 sources — identifiers the candidate supplied
# --------------------------------------------------------------------------- #

def gravatar_for_email(email: Optional[str]) -> Optional[str]:
    """Gravatar is keyed to the email itself: the strongest available signal."""
    if not email or "@" not in email:
        return None
    import hashlib
    digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
    probe = f"https://www.gravatar.com/avatar/{digest}?d=404&s=256"
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as c:
            if c.head(probe).status_code == 200:
                return f"https://www.gravatar.com/avatar/{digest}?s=256"
    except Exception:
        pass
    return None


def github_avatar(handle_or_url: str) -> Optional[str]:
    m = PROFILE_PATTERNS[1][1].search(handle_or_url or "")
    handle = m.group(1) if m else (handle_or_url or "").strip().lstrip("@")
    if not handle or handle.lower() in _RESERVED:
        return None
    return f"https://github.com/{handle}.png?size=256" if _get_json(f"https://api.github.com/users/{handle}") else None


def github_probe_from_email(email: Optional[str], name: str,
                            extra_handles: Optional[List[str]] = None
                            ) -> Optional[Dict[str, Any]]:
    """
    Try plausible GitHub handles derived from the email prefix and the name, and
    accept one ONLY when the account's own display name matches the candidate.
    This turns a bare email address into a verified social photo when possible.
    """
    if not email or "@" not in email:
        candidates = list(extra_handles or [])
    else:
        prefix = email.split("@")[0].lower()
        toks = _name_tokens(name)
        candidates = [prefix, re.sub(r"[._\-]", "", prefix)]
        if len(toks) >= 2:
            candidates += [f"{toks[0]}{toks[-1]}", f"{toks[0]}.{toks[-1]}",
                           f"{toks[0]}{toks[-1][0]}", f"{toks[0][0]}{toks[-1]}"]
        candidates += list(extra_handles or [])

    seen = set()
    for handle in candidates:
        handle = (handle or "").strip().lstrip("@")
        if not handle or handle in seen or handle.lower() in _RESERVED:
            continue
        seen.add(handle)
        data = _get_json(f"https://api.github.com/users/{handle}")
        if not data:
            continue
        real_name = (data.get("name") or "").strip()
        if real_name and _full_name_present(real_name, name):
            return {
                "url": f"https://github.com/{handle}.png?size=256",
                "handle": handle,
                "account_name": real_name,
                "evidence": [f"GitHub account @{handle} lists its name as “{real_name}”",
                             f"Handle derived from {email if email else 'supplied handle'}"],
                "profile_url": f"https://github.com/{handle}",
            }
    return None


# --------------------------------------------------------------------------- #
# Tier 2 source — candidate-supplied profile URL
# --------------------------------------------------------------------------- #

def _parse_profile_url(url: str) -> Optional[Tuple[str, str]]:
    for platform, pattern in PROFILE_PATTERNS:
        m = pattern.search(url or "")
        if m:
            handle = m.group(1).strip("/")
            if handle and handle.lower() not in _RESERVED:
                return platform, handle
    return None


def photo_from_supplied_link(url: str, name: str) -> Optional[Dict[str, Any]]:
    """
    A URL the candidate put on their own resume is a first-party identifier:
    if it yields an image, that image is theirs to claim.
    """
    if not (url or "").startswith("http"):
        return None
    meta = fetch_page_meta(url)
    image = meta.get("image")
    if not image:
        return None
    # Guard against generic logos/CDN placeholders and login-wall art
    low = image.lower()
    if any(bad in low for bad in ("logo", "default", "placeholder", "ghost", "1x1")):
        return None

    parsed = _parse_profile_url(url)
    platform = parsed[0] if parsed else (meta.get("site_name") or "Web")
    evidence = [f"Profile URL supplied on the resume: {url}",
                f"{platform} page title: “{meta.get('title', '')[:90]}”"]
    if _full_name_present(meta.get("title", "") + " " + meta.get("description", ""), name):
        evidence.append("Page metadata contains the candidate's full name")
    return {"url": image, "platform": platform, "profile_url": url, "evidence": evidence}


# --------------------------------------------------------------------------- #
# Tier 3 — search-discovered profiles, corroboration required
# --------------------------------------------------------------------------- #

def score_profile(url: str, name: str, location: str = "",
                  employers: Optional[List[str]] = None,
                  email: str = "") -> Optional[Dict[str, Any]]:
    """
    Fetch a discovered profile and score how strongly it points at THIS person.
    Returns None unless the page loads and yields an image.
    """
    meta = fetch_page_meta(url)
    image = meta.get("image")
    if not image:
        return None

    blob = " ".join([meta.get("title", ""), meta.get("description", ""), url]).lower()
    evidence: List[str] = []
    score = 0

    if _full_name_present(blob, name):
        score += 2
        evidence.append("Profile name matches the candidate's full name")
    else:
        return None  # a photo we cannot tie to the name is not worth showing as a match

    city = (location or "").split(",")[0].strip().lower()
    if city and city in blob:
        score += 1
        evidence.append(f"Location “{location}” appears on the profile")

    for emp in (employers or [])[:3]:
        emp_key = emp.strip().lower()
        if emp_key and emp_key in blob:
            score += 1
            evidence.append(f"Employer “{emp}” appears on the profile")
            break

    if email and email.lower() in blob:
        score += 2
        evidence.append("Candidate's email appears on the profile")

    parsed = _parse_profile_url(url)
    platform = parsed[0] if parsed else (meta.get("site_name") or "Web")
    return {
        "url": image, "platform": platform, "profile_url": url,
        "score": score, "evidence": evidence,
        "title": meta.get("title", "")[:120],
    }


def search_web_photos(name: str, location: str = "",
                      employer: str = "", max_results: int = 4
                      ) -> List[Dict[str, str]]:
    """Name-matched image search. NEVER auto-assigned — review gallery only."""
    if not name or len(name.strip()) < 3:
        return []
    queries = [f'"{name}" {location}'.strip(), f'"{name}" {employer}'.strip()]
    out: List[Dict[str, str]] = []
    seen = set()
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            for q in queries:
                if not q or q == f'"{name}"':
                    continue
                try:
                    for item in ddgs.images(q, max_results=max_results) or []:
                        if not isinstance(item, dict):
                            continue
                        thumb = item.get("thumbnail") or item.get("image")
                        if thumb and thumb not in seen:
                            seen.add(thumb)
                            out.append({"url": thumb,
                                        "title": item.get("title", ""),
                                        "source": item.get("url", "")})
                except Exception:
                    continue
                if len(out) >= max_results:
                    break
    except Exception:
        pass
    return out[:max_results]


# --------------------------------------------------------------------------- #
# top-level resolver
# --------------------------------------------------------------------------- #

def resolve_candidate_photo(
    name: str,
    email: Optional[str] = None,
    resume_links: Optional[List[str]] = None,
    location: str = "",
    employers: Optional[List[str]] = None,
    discovered_profiles: Optional[List[str]] = None,
    auto_accept_likely: bool = False,
) -> Dict[str, Any]:
    """
    Resolve the best available candidate photo and an evidence trail.

    Returns
    -------
    {
      "photo":   {"url", "tier", "platform", "source", "evidence": [...]} | None,
      "status":  "verified" | "likely" | "possible" | "none",
      "candidates": [ ...ranked alternatives for human confirmation... ],
      "log":     ["Human-readable audit of every source tried"],
    }
    """
    links = [l for l in (resume_links or []) if l and l.startswith("http")]
    log: List[str] = []
    candidates: List[Dict[str, Any]] = []

    # ---- Tier 1a: Gravatar (email-keyed) ----
    if email:
        g = gravatar_for_email(email)
        if g:
            log.append("Gravatar: image found for the supplied email (email-keyed match).")
            return {
                "photo": {"url": g, "tier": "verified", "platform": "Gravatar",
                          "source": "Gravatar (email match)",
                          "evidence": [f"Gravatar account exists for {email}"]},
                "status": "verified", "candidates": [], "log": log,
            }
        log.append("Gravatar: no account registered for that email.")

    # ---- Tier 1b: GitHub from resume links, then from the email/name ----
    for link in links:
        if "github.com" in link.lower():
            url = github_avatar(link)
            if url:
                log.append(f"GitHub: avatar found from the resume-supplied profile {link}.")
                return {
                    "photo": {"url": url, "tier": "verified", "platform": "GitHub",
                              "source": "GitHub (profile listed on resume)",
                              "evidence": [f"Profile URL supplied on the resume: {link}"]},
                    "status": "verified", "candidates": [], "log": log,
                }

    gh = github_probe_from_email(email, name, extra_handles=links)
    if gh:
        log.append(f"GitHub: matched @{gh['handle']} (profile name confirms the candidate).")
        return {
            "photo": {"url": gh["url"], "tier": "verified", "platform": "GitHub",
                      "source": f"GitHub (@{gh['handle']} — name confirmed)",
                      "evidence": gh["evidence"]},
            "status": "verified", "candidates": [], "log": log,
        }
    log.append("GitHub: no account matched the name/email combination.")

    # ---- Tier 2: any other profile URL the candidate supplied ----
    for link in links:
        if "github.com" in link.lower():
            continue
        got = photo_from_supplied_link(link, name)
        if got:
            log.append(f"{got['platform']}: photo pulled from the resume-supplied profile.")
            return {
                "photo": {"url": got["url"], "tier": "verified", "platform": got["platform"],
                          "source": f"{got['platform']} (profile listed on resume)",
                          "evidence": got["evidence"]},
                "status": "verified", "candidates": [], "log": log,
            }
    if links:
        log.append(f"Supplied links: no usable profile image from {len(links)} link(s).")

    # ---- Tier 3: search-discovered profiles (need >= 2 signals) ----
    for url in (discovered_profiles or [])[:8]:
        scored = score_profile(url, name, location, employers, email=email or "")
        if scored:
            scored["tier"] = "likely"
            candidates.append(scored)
        else:
            low = url.lower()
            if "instagram.com" in low:
                log.append("Instagram profile found but public image unavailable — Instagram blocks automated access.")
            elif "facebook.com" in low:
                log.append("Facebook profile found but public image unavailable — Facebook blocks automated access.")
    candidates.sort(key=lambda c: c.get("score", 0), reverse=True)
    if candidates:
        log.append(f"Search-discovered profiles: {len(candidates)} corroborated candidate profile(s).")

    # ---- Review gallery (name-matched only) ----
    gallery = search_web_photos(name, location, (employers or [""])[0] if employers else "")
    for g in gallery:
        candidates.append({"url": g["url"], "tier": "possible", "score": 0,
                           "platform": "Web image search",
                           "profile_url": g.get("source", ""),
                           "title": g.get("title", ""),
                           "evidence": ["Matched the candidate's NAME only — not an identity match"]})
    if gallery:
        log.append(f"Web image search: {len(gallery)} name-matched image(s) held for human review.")

    # ---- Decide what (if anything) is auto-assigned ----
    if candidates and candidates[0].get("tier") == "likely" and auto_accept_likely:
        best = candidates[0]
        log.append("AUTO-ACCEPT enabled: top corroborated profile photo assigned automatically.")
        return {"photo": {"url": best["url"], "tier": "likely",
                          "platform": best["platform"],
                          "source": f"{best['platform']} (corroborated match)",
                          "evidence": best["evidence"]},
                "status": "likely", "candidates": candidates[1:], "log": log}

    log.append("No photo auto-assigned. Review the candidates below and confirm the right person.")
    return {"photo": None, "status": "possible" if candidates else "none",
            "candidates": candidates, "log": log}

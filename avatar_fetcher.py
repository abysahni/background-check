"""
Candidate Avatar & Public Photo Discovery Engine
Fetches public candidate photos using:
1. Live Web Image Search (DuckDuckGo / Bing Image CDN)
2. Gravatar (Email MD5 check)
3. GitHub Public Avatar
4. Open Graph (og:image) Scraper
5. Fallback Initials Badge
"""

import hashlib
import re
import urllib.parse
from typing import Optional, Dict, List, Any
import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}


def get_initials_avatar(name: str) -> str:
    """Generate a clean, high-resolution initials badge as fallback."""
    clean_name = urllib.parse.quote(name.strip() if name else "Candidate")
    return f"https://ui-avatars.com/api/?name={clean_name}&background=2563eb&color=ffffff&size=256&bold=true&rounded=true"


def check_gravatar(email: str) -> Optional[str]:
    """Check if the candidate's email is registered on Gravatar."""
    if not email or "@" not in email:
        return None
    email_clean = email.strip().lower()
    email_hash = hashlib.md5(email_clean.encode("utf-8")).hexdigest()
    gravatar_url = f"https://www.gravatar.com/avatar/{email_hash}?d=404&s=256"
    try:
        with httpx.Client(timeout=4.0, headers=HEADERS, follow_redirects=True) as client:
            resp = client.head(gravatar_url)
            if resp.status_code == 200:
                return gravatar_url
    except Exception:
        pass
    return None


def extract_github_username(text: str) -> Optional[str]:
    """Extract GitHub username from URL or handle."""
    if not text:
        return None
    clean = text.strip()
    match = re.search(r"github\.com/([a-zA-Z0-9_-]+)", clean, re.IGNORECASE)
    if match:
        user = match.group(1)
        if user.lower() not in ["explore", "topics", "trending", "features", "marketplace", "about"]:
            return user
    if clean.startswith("@"):
        return clean[1:]
    if re.match(r"^[a-zA-Z0-9_-]{1,39}$", clean) and not clean.startswith("-"):
        return clean
    return None


def check_github_avatar(username_or_url: str) -> Optional[str]:
    """Get public GitHub avatar URL if user exists."""
    username = extract_github_username(username_or_url)
    if not username:
        return None
    url = f"https://github.com/{username}.png?size=256"
    try:
        with httpx.Client(timeout=4.0, headers=HEADERS, follow_redirects=True) as client:
            resp = client.head(url)
            if resp.status_code == 200:
                return url
    except Exception:
        pass
    return None


def search_candidate_web_photos(
    name: str,
    location: Optional[str] = None,
    employer: Optional[str] = None,
    max_results: int = 4
) -> List[Dict[str, str]]:
    """Search the public web for candidate face photos, portraits, and thumbnails."""
    if not name or len(name.strip()) < 2:
        return []
    
    clean_name = name.strip()
    loc = location.strip() if location else ""
    emp = employer.strip() if employer else ""

    queries_to_try = [
        f'"{clean_name}" {loc} {emp}'.strip(),
        f'"{clean_name}" {loc}'.strip(),
        f'"{clean_name}" {emp}'.strip(),
        f'{clean_name} portrait OR photo OR profile'.strip(),
    ]

    discovered = []
    seen_urls = set()

    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            for q in queries_to_try:
                if not q or q == f'"{clean_name}"':
                    continue
                try:
                    raw_imgs = ddgs.images(q, max_results=max_results)
                    if raw_imgs:
                        for item in raw_imgs:
                            if not isinstance(item, dict):
                                continue
                            thumb = item.get("thumbnail") or item.get("image")
                            high_res = item.get("image") or thumb
                            if thumb and thumb not in seen_urls:
                                seen_urls.add(thumb)
                                discovered.append({
                                    "url": thumb,
                                    "high_res": high_res,
                                    "title": item.get("title", f"Photo for {clean_name}"),
                                    "source": item.get("url", ""),
                                })
                        if len(discovered) >= max_results:
                            break
                except Exception:
                    continue
    except Exception:
        pass

    return discovered[:max_results]


def resolve_candidate_avatar(
    name: str,
    email: Optional[str] = None,
    social_links: Optional[List[str]] = None,
    github_handle: Optional[str] = None,
    location: Optional[str] = None,
    employer: Optional[str] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Resolve best candidate avatar and photo gallery using multi-source discovery:
    1. Gravatar (email-based, high accuracy)
    2. GitHub profile
    3. Public Web Photo Discovery (searches DDG / Bing Image CDN)
    4. Fallback Initials Badge
    """
    gallery: List[Dict[str, str]] = []

    # 1. Gravatar
    if email:
        gravatar = check_gravatar(email)
        if gravatar:
            return {
                "url": gravatar,
                "source": "Gravatar (Email Match)",
                "confidence": "High",
                "gallery": [{"url": gravatar, "title": "Gravatar Profile Photo", "source": email}]
            }

    # 2. GitHub
    if github_handle:
        gh_avatar = check_github_avatar(github_handle)
        if gh_avatar:
            return {
                "url": gh_avatar,
                "source": f"GitHub (@{github_handle})",
                "confidence": "High",
                "gallery": [{"url": gh_avatar, "title": "GitHub Profile Photo", "source": f"https://github.com/{github_handle}"}]
            }

    if social_links:
        for link in social_links:
            if "github.com" in link.lower():
                gh_avatar = check_github_avatar(link)
                if gh_avatar:
                    return {
                        "url": gh_avatar,
                        "source": "GitHub Profile",
                        "confidence": "High",
                        "gallery": [{"url": gh_avatar, "title": "GitHub Profile Photo", "source": link}]
                    }

    # 3. Live Public Web Image Search
    web_photos = search_candidate_web_photos(name=name, location=location, employer=employer, max_results=4)
    if web_photos:
        primary_photo = web_photos[0]
        return {
            "url": primary_photo["url"],
            "source": f"Web Photo ({primary_photo.get('title', 'Public Profile')[:35]}...)",
            "confidence": "Medium (Web Discovery)",
            "gallery": web_photos
        }

    # 4. Fallback Initials Badge
    fallback_url = get_initials_avatar(name)
    return {
        "url": fallback_url,
        "source": "Generated Name Badge",
        "confidence": "Fallback",
        "gallery": []
    }

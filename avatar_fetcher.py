"""
Candidate Avatar & Display Photo Fetcher
Fetches public profile photos to verify identity and match the candidate's face
using Gravatar, GitHub, and Open Graph (og:image) metadata from public profiles.
"""

import hashlib
import re
import urllib.parse
from typing import Optional, Dict, List
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
    # match github.com/username
    match = re.search(r"github\.com/([a-zA-Z0-9_-]+)", clean, re.IGNORECASE)
    if match:
        user = match.group(1)
        if user.lower() not in ["explore", "topics", "trending", "features", "marketplace", "about"]:
            return user
    if clean.startswith("@"):
        return clean[1:]
    # Check if plain valid GitHub handle
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


def extract_og_image(url: str) -> Optional[str]:
    """Extract Open Graph or Twitter image from public URL."""
    if not url or not url.startswith("http"):
        return None
    # Skip domains that block unauthenticated head or return generic placeholder
    skip_domains = ["facebook.com", "instagram.com"]
    if any(domain in url.lower() for domain in skip_domains):
        return None

    try:
        with httpx.Client(timeout=5.0, headers=HEADERS, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code != 200 or not resp.text:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            
            # Check og:image or twitter:image
            for meta_prop in ["og:image", "twitter:image", "og:image:url"]:
                tag = soup.find("meta", attrs={"property": meta_prop}) or soup.find("meta", attrs={"name": meta_prop})
                if tag and tag.get("content"):
                    img_url = tag["content"].strip()
                    # Resolve relative URLs
                    img_url = urllib.parse.urljoin(url, img_url)
                    # Filter out obvious non-avatars (standard platform logos / favicons)
                    lower_img = img_url.lower()
                    if not any(bad in lower_img for bad in ["logo-", "site-logo", "favicon", "default_avatar", "badge"]):
                        return img_url
    except Exception:
        pass
    return None


def resolve_candidate_avatar(
    name: str,
    email: Optional[str] = None,
    social_links: Optional[List[str]] = None,
    github_handle: Optional[str] = None,
) -> Dict[str, str]:
    """
    Resolve best candidate avatar using cascading sources:
    1. Gravatar (email-based, high accuracy)
    2. GitHub profile
    3. Open Graph image from personal site / public profiles
    4. Clean modern initials avatar fallback
    """
    # 1. Gravatar
    if email:
        gravatar = check_gravatar(email)
        if gravatar:
            return {"url": gravatar, "source": "Gravatar (Email Match)", "confidence": "High"}

    # 2. GitHub
    if github_handle:
        gh_avatar = check_github_avatar(github_handle)
        if gh_avatar:
            return {"url": gh_avatar, "source": f"GitHub (@{github_handle})", "confidence": "High"}

    if social_links:
        for link in social_links:
            if "github.com" in link.lower():
                gh_avatar = check_github_avatar(link)
                if gh_avatar:
                    return {"url": gh_avatar, "source": "GitHub Profile", "confidence": "High"}

        # 3. Open Graph image from personal portfolio or blogs
        for link in social_links:
            if any(dom in link.lower() for dom in ["medium.com", "substack.com", "dev.to", "about.me"]) or (
                not any(big in link.lower() for big in ["linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com"])
            ):
                og_img = extract_og_image(link)
                if og_img:
                    return {"url": og_img, "source": f"Public Profile ({urllib.parse.urlparse(link).netloc})", "confidence": "Medium"}

    # 4. Fallback Initials
    return {
        "url": get_initials_avatar(name),
        "source": "Generated Name Badge",
        "confidence": "Fallback",
    }

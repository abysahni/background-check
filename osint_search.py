"""
Multi-Track OSINT & Public Search Engine
Performs concurrent targeted searches across professional networks, social media,
past employer validation, and reference cross-checks.
Uses DuckDuckGo search (free, no API key required) with SSL compatibility patch,
intelligent URL classification, and optional Serper.dev Google API integration.
"""

import concurrent.futures
import os
import re
import ssl
import urllib.parse
import warnings
from typing import Dict, List, Any, Optional
import httpx

warnings.filterwarnings("ignore", category=RuntimeWarning)

# SSL compatibility patch for LibreSSL / macOS Python 3.9
try:
    import ddgs.http_client2
    def _safe_ssl_context(verify=True):
        return ssl.create_default_context()
    ddgs.http_client2._get_random_ssl_context = _safe_ssl_context
except Exception:
    pass


def derive_handles_from_email(email: Optional[str]) -> List[str]:
    """Extract likely social handles from email prefix."""
    if not email or "@" not in email:
        return []
    prefix = email.split("@")[0].lower()
    handles = [prefix]
    clean = re.sub(r"[._-]", "", prefix)
    if clean != prefix and len(clean) >= 3:
        handles.append(clean)
    return handles


def search_serper(query: str, api_key: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Execute Google search via Serper.dev API if key is provided."""
    results = []
    try:
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": max_results}
        with httpx.Client(timeout=6.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("organic", []):
                    results.append({
                        "title": item.get("title", ""),
                        "href": item.get("link", ""),
                        "body": item.get("snippet", "")
                    })
    except Exception:
        pass
    return results


def search_ddg(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Execute a single DuckDuckGo search query safely with browser TLS fingerprinting."""
    results = []
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            raw = list(ddgs.text(query, max_results=max_results))
            for item in raw:
                href = item.get("href", "").strip()
                title = item.get("title", "").strip()
                if href and title and not any(bad in href for bad in ["duckduckgo.com", "bing.com/aclick", "r.search.yahoo"]):
                    results.append({
                        "title": title,
                        "href": href,
                        "body": item.get("body", "")
                    })
    except Exception:
        # Fallback to direct HTTP request
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
            with httpx.Client(timeout=6.0, headers=headers, follow_redirects=True) as client:
                resp = client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    links = soup.find_all("a", class_="result-link")
                    snippets = soup.find_all("td", class_="result-snippet")
                    for i in range(min(len(links), max_results)):
                        href = links[i].get("href", "").strip()
                        if "uddg=" in href:
                            qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                            if "uddg" in qs:
                                href = qs["uddg"][0]
                        title = links[i].text.strip()
                        snippet = snippets[i].text.strip() if i < len(snippets) else ""
                        if href and title:
                            results.append({"title": title, "href": href, "body": snippet})
        except Exception:
            pass

    return results


def classify_url_platform(url: str, title: str) -> Optional[Dict[str, str]]:
    """Determine the social or professional platform from the URL structure."""
    u = url.lower()
    if "linkedin.com" in u:
        return {"platform": "LinkedIn", "category": "Professional", "badge": "💼 LinkedIn"}
    elif "github.com" in u and not any(x in u for x in ["github.com/topics", "github.com/features"]):
        return {"platform": "GitHub", "category": "Professional", "badge": "💻 GitHub"}
    elif "instagram.com" in u and not any(x in u for x in ["instagram.com/p/", "instagram.com/reel/"]):
        return {"platform": "Instagram", "category": "Social", "badge": "📸 Instagram"}
    elif "facebook.com" in u and not any(x in u for x in ["facebook.com/sharer", "facebook.com/login"]):
        return {"platform": "Facebook", "category": "Social", "badge": "👥 Facebook"}
    elif "twitter.com" in u or "x.com" in u:
        return {"platform": "Twitter / X", "category": "Social", "badge": "🐦 X / Twitter"}
    elif "reddit.com" in u:
        return {"platform": "Reddit", "category": "Social", "badge": "💬 Reddit"}
    elif "tiktok.com" in u:
        return {"platform": "TikTok", "category": "Social", "badge": "🎵 TikTok"}
    elif "threads.net" in u:
        return {"platform": "Threads", "category": "Social", "badge": "🧵 Threads"}
    elif any(d in u for d in ["medium.com", "substack.com", "wordpress.com", "blogspot.com", "dev.to"]):
        return {"platform": "Articles & Blogs", "category": "Publications", "badge": "📝 Article/Blog"}
    return None


def run_candidate_osint(
    candidate_name: str,
    location: Optional[str] = None,
    past_employers: Optional[List[str]] = None,
    references: Optional[List[Dict[str, Any]]] = None,
    email: Optional[str] = None,
    additional_handles: Optional[List[str]] = None,
    serper_api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run high-yield multi-track concurrent OSINT investigation:
    1. Professional Profiles (LinkedIn, GitHub, Portfolio)
    2. Social Networks (X/Twitter, Instagram, Facebook, Reddit, TikTok)
    3. Employer Validation (Check if previous stores/companies exist)
    4. Reference Cross-Check (Confirm reference actually worked at employer)
    """
    c_name = candidate_name.strip()
    loc = location.strip() if location else ""
    first_emp = past_employers[0].strip() if past_employers and len(past_employers) > 0 else ""

    queries = {}

    # 1. LinkedIn Targets
    queries["linkedin_1"] = {"target": "LinkedIn", "query": f"{c_name} {loc} {first_emp} LinkedIn".strip()}
    queries["linkedin_2"] = {"target": "LinkedIn", "query": f"site:linkedin.com {c_name} {loc}".strip()}

    # 2. Instagram
    queries["instagram"] = {"target": "Instagram", "query": f"{c_name} {loc} Instagram".strip()}

    # 3. Facebook
    queries["facebook"] = {"target": "Facebook", "query": f"{c_name} {loc} Facebook".strip()}

    # 4. Twitter / X
    queries["twitter"] = {"target": "Twitter / X", "query": f"{c_name} {loc} Twitter OR X".strip()}

    # 5. Reddit
    queries["reddit"] = {"target": "Reddit", "query": f"{c_name} {loc} Reddit".strip()}

    # 6. News & Public mentions
    queries["news"] = {"target": "Public News", "query": f'"{c_name}" {loc} {first_emp}'.strip()}

    # 7. Employer Legitimacy
    if past_employers:
        for idx, emp in enumerate(past_employers[:3]):
            if emp and len(emp.strip()) > 1:
                queries[f"employer_{idx}"] = {
                    "target": f"Employer: {emp.strip()}",
                    "query": f'"{emp.strip()}" {loc} store OR company OR retail OR business'.strip(),
                }

    # 8. Reference Cross-Verification
    if references:
        for idx, ref in enumerate(references[:3]):
            ref_name = ref.get("name", "").strip()
            ref_comp = ref.get("company", "").strip() or first_emp
            if ref_name:
                queries[f"reference_{idx}"] = {
                    "target": f"Reference: {ref_name}",
                    "query": f'"{ref_name}" "{ref_comp}"'.strip(),
                }

    search_results: Dict[str, Any] = {
        "professional": [],
        "social": [],
        "employer_validation": {},
        "reference_verification": {},
        "web_mentions": [],
        "raw_findings": []
    }

    seen_urls = set()

    def execute_query(key: str, info: Dict[str, str]):
        q = info["query"]
        if serper_api_key and serper_api_key.strip():
            raw = search_serper(q, serper_api_key.strip(), max_results=4)
        else:
            raw = search_ddg(q, max_results=4)
        return key, info, raw

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(execute_query, k, v) for k, v in queries.items()]

        for f in concurrent.futures.as_completed(futures):
            try:
                key, info, items = f.result()
                target = info["target"]

                for item in items:
                    url = item["href"]
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    entry = {
                        "platform": target,
                        "title": item["title"],
                        "url": url,
                        "snippet": item["body"]
                    }

                    # Classify URL
                    classified = classify_url_platform(url, item["title"])
                    if classified:
                        entry["platform"] = classified["platform"]
                        entry["badge"] = classified["badge"]
                        if classified["category"] == "Professional":
                            search_results["professional"].append(entry)
                        elif classified["category"] == "Social":
                            search_results["social"].append(entry)
                        elif classified["category"] == "Publications":
                            search_results["web_mentions"].append(entry)
                    else:
                        if target.startswith("Employer:"):
                            emp_name = target.replace("Employer:", "").strip()
                            if emp_name not in search_results["employer_validation"]:
                                search_results["employer_validation"][emp_name] = []
                            search_results["employer_validation"][emp_name].append(item)
                        elif target.startswith("Reference:"):
                            ref_name = target.replace("Reference:", "").strip()
                            if ref_name not in search_results["reference_verification"]:
                                search_results["reference_verification"][ref_name] = []
                            search_results["reference_verification"][ref_name].append(item)
                        else:
                            search_results["web_mentions"].append(entry)

                    search_results["raw_findings"].append({
                        "target": target,
                        "platform": entry.get("platform", target),
                        "title": item["title"],
                        "url": url,
                        "snippet": item["body"]
                    })
            except Exception:
                pass

    return search_results

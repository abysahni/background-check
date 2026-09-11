"""
Multi-Track OSINT & Public Search Engine
Performs concurrent targeted searches across professional networks, social media,
past employer validation, and reference cross-checks.
Uses DuckDuckGo search (free, no API key required) with robust fallback mechanisms.
"""

import concurrent.futures
import re
import urllib.parse
import warnings
from typing import Dict, List, Any, Optional
import httpx

warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*duckduckgo_search.*")


def derive_handles_from_email(email: Optional[str]) -> List[str]:
    """Extract likely social handles from email prefix."""
    if not email or "@" not in email:
        return []
    prefix = email.split("@")[0].lower()
    handles = [prefix]
    # Remove dots or underscores
    clean = re.sub(r"[._-]", "", prefix)
    if clean != prefix and len(clean) >= 3:
        handles.append(clean)
    return handles


def search_ddg(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Execute a single DuckDuckGo search query reliably using lite endpoint and fallback."""
    results = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    
    # 1. Primary: lite.duckduckgo.com (Fastest, zero captcha / bot challenges)
    try:
        from bs4 import BeautifulSoup
        with httpx.Client(timeout=8.0, headers=headers, follow_redirects=True) as client:
            resp = client.post("https://lite.duckduckgo.com/lite/", data={"q": query})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                links = soup.find_all("a", class_="result-link")
                snippets = soup.find_all("td", class_="result-snippet")
                
                count = min(len(links), max_results)
                for i in range(count):
                    title = links[i].text.strip()
                    href = links[i].get("href", "").strip()
                    
                    # Decode target URL if wrapped in DuckDuckGo redirect
                    if "uddg=" in href:
                        parsed_url = urllib.parse.urlparse(href)
                        qs = urllib.parse.parse_qs(parsed_url.query)
                        if "uddg" in qs:
                            href = qs["uddg"][0]
                    
                    snippet = snippets[i].text.strip() if i < len(snippets) else ""
                    if href and title:
                        results.append({
                            "title": title,
                            "href": href,
                            "body": snippet
                        })
        if resp.status_code == 200:
            return results
    except Exception:
        pass

    # 2. Secondary fallback: ddgs / duckduckgo-search package
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, max_results=max_results))
            for item in raw_results:
                results.append({
                    "title": item.get("title", ""),
                    "href": item.get("href", ""),
                    "body": item.get("body", "")
                })
    except Exception:
        pass

    return results



def check_direct_profile(platform_name: str, url: str) -> Optional[Dict[str, Any]]:
    """Quickly check if a direct platform profile exists (e.g. GitHub or Reddit)."""
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        with httpx.Client(timeout=4.0, headers=headers, follow_redirects=True) as client:
            resp = client.head(url)
            if resp.status_code == 200:
                return {
                    "platform": platform_name,
                    "url": url,
                    "title": f"{platform_name} Profile Found",
                    "snippet": f"Active public profile verified at {url}",
                    "confidence": "High (Direct Match)"
                }
    except Exception:
        pass
    return None


def run_candidate_osint(
    candidate_name: str,
    location: Optional[str] = None,
    past_employers: Optional[List[str]] = None,
    references: Optional[List[Dict[str, Any]]] = None,
    email: Optional[str] = None,
    additional_handles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Run multi-track concurrent OSINT investigation:
    1. Professional Profiles (LinkedIn, GitHub, Portfolio)
    2. Social Networks (X/Twitter, Instagram, Facebook, Reddit)
    3. Employer Validation (Check if previous stores/companies exist)
    4. Reference Cross-Check (Confirm reference actually worked at employer)
    5. Direct Handle Discovery
    """
    loc_clause = f'"{location.strip()}"' if location and location.strip() else ""
    first_employer = past_employers[0] if past_employers and len(past_employers) > 0 else ""
    first_emp_clause = f'"{first_employer.strip()}"' if first_employer else ""

    # Define Query Tracks
    queries = {}

    # Track 1: LinkedIn Professional
    queries["linkedin"] = {
        "category": "Professional",
        "platform": "LinkedIn",
        "query": f'site:linkedin.com/in/ "{candidate_name}" {loc_clause} {first_emp_clause}'.strip(),
    }

    # Track 2: GitHub / Portfolio
    queries["github"] = {
        "category": "Professional",
        "platform": "GitHub",
        "query": f'site:github.com "{candidate_name}"'.strip(),
    }

    # Track 3: Twitter / X
    queries["twitter"] = {
        "category": "Social",
        "platform": "Twitter / X",
        "query": f'(site:twitter.com OR site:x.com) "{candidate_name}" {loc_clause}'.strip(),
    }

    # Track 4: Instagram
    queries["instagram"] = {
        "category": "Social",
        "platform": "Instagram",
        "query": f'site:instagram.com "{candidate_name}" {loc_clause}'.strip(),
    }

    # Track 5: Facebook
    queries["facebook"] = {
        "category": "Social",
        "platform": "Facebook",
        "query": f'site:facebook.com "{candidate_name}" {loc_clause}'.strip(),
    }

    # Track 6: Blogs / Publications / Medium
    queries["blogs"] = {
        "category": "Publications",
        "platform": "Articles & Blogs",
        "query": f'(site:medium.com OR site:substack.com OR site:wordpress.com) "{candidate_name}"'.strip(),
    }

    # Track 7: Employer Legitimacy Checks (Up to 3 employers)
    if past_employers:
        for idx, emp in enumerate(past_employers[:3]):
            if emp and len(emp.strip()) > 1:
                queries[f"employer_{idx}"] = {
                    "category": "Employer Validation",
                    "platform": emp.strip(),
                    "query": f'"{emp.strip()}" {loc_clause} (store OR company OR retail OR business OR location)'.strip(),
                }

    # Track 8: Reference Verification Checks
    if references:
        for idx, ref in enumerate(references[:3]):
            ref_name = ref.get("name", "").strip()
            ref_comp = ref.get("company", "").strip() or first_employer
            if ref_name:
                queries[f"reference_{idx}"] = {
                    "category": "Reference Verification",
                    "platform": ref_name,
                    "query": f'"{ref_name}" "{ref_comp}"'.strip(),
                }

    # Direct Handle checks (Reddit, GitHub, Twitter)
    derived_handles = derive_handles_from_email(email)
    if additional_handles:
        for h in additional_handles:
            clean_h = h.strip().lstrip("@")
            if clean_h and clean_h not in derived_handles:
                derived_handles.append(clean_h)

    # Execute all searches concurrently with ThreadPoolExecutor
    search_results: Dict[str, Any] = {
        "professional": [],
        "social": [],
        "employer_validation": {},
        "reference_verification": {},
        "direct_handles": [],
        "raw_findings": []
    }

    def execute_query(key: str, info: Dict[str, str]):
        raw = search_ddg(info["query"], max_results=4)
        return key, info, raw

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(execute_query, k, v) for k, v in queries.items()]
        
        # Check direct handles in parallel
        handle_futures = []
        for handle in derived_handles[:2]:
            handle_futures.append(executor.submit(check_direct_profile, "GitHub", f"https://github.com/{handle}"))
            handle_futures.append(executor.submit(check_direct_profile, "Reddit", f"https://www.reddit.com/user/{handle}"))

        for f in concurrent.futures.as_completed(futures):
            try:
                key, info, items = f.result()
                category = info["category"]
                platform = info["platform"]

                if category == "Professional":
                    for item in items:
                        search_results["professional"].append({
                            "platform": platform,
                            "title": item["title"],
                            "url": item["href"],
                            "snippet": item["body"]
                        })
                elif category == "Social":
                    for item in items:
                        search_results["social"].append({
                            "platform": platform,
                            "title": item["title"],
                            "url": item["href"],
                            "snippet": item["body"]
                        })
                elif category == "Employer Validation":
                    search_results["employer_validation"][platform] = items
                elif category == "Reference Verification":
                    search_results["reference_verification"][platform] = items
                
                for item in items:
                    search_results["raw_findings"].append({
                        "category": category,
                        "platform": platform,
                        "title": item["title"],
                        "url": item["href"],
                        "snippet": item["body"]
                    })
            except Exception:
                pass

        for hf in concurrent.futures.as_completed(handle_futures):
            try:
                h_res = hf.result()
                if h_res:
                    search_results["direct_handles"].append(h_res)
                    if h_res["platform"] == "GitHub":
                        search_results["professional"].append(h_res)
                    else:
                        search_results["social"].append(h_res)
            except Exception:
                pass

    return search_results

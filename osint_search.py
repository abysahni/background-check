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
from typing import Dict, List, Any, Optional, Tuple
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


DIRECTORY_INDICATORS = [
    "/pub/dir/",
    "/dir/",
    "profiles",
    "employee directory",
    "people named",
    "directory",
]


def attribute_result(
    result: Dict[str, Any],
    name: str,
    location: str = "",
    employers: Optional[List[str]] = None,
    email: str = "",
) -> Tuple[str, List[str]]:
    """
    Return ("attributed" | "unattributed", [evidence]) for a search result.

    Rules:
      - Full name must appear (all tokens), not just one shared token.
        'Delaney' alone is NOT a match.
      - +1 signal each for: location city, any claimed employer, the candidate's email.
      - attributed   = full name AND (>=1 supporting signal)
      - unattributed = everything else
      - Aggregator/directory URLs are neither:
        '/pub/dir/', '/dir/', 'profiles', 'Employee Directory', 'people named'
    """
    url = (result.get("url") or result.get("href") or "").strip()
    title = (result.get("title") or "").strip()
    snippet = (result.get("snippet") or result.get("body") or "").strip()
    blob = f"{title} {snippet} {url}".lower()

    # Aggregator / Directory Check
    url_low = url.lower()
    title_low = title.lower()
    if any(ind in url_low or ind in title_low for ind in DIRECTORY_INDICATORS):
        return "unattributed", ["Directory/aggregator page — excluded from candidate attribution"]

    # Full Name Check
    clean_name = re.sub(r"[^\w\s]", " ", name or "").lower()
    name_tokens = [tok for tok in clean_name.split() if len(tok) >= 2]
    if not name_tokens:
        return "unattributed", ["No candidate name provided for attribution"]

    full_name_matched = all(re.search(r"\b" + re.escape(tok) + r"\b", blob) for tok in name_tokens)
    if not full_name_matched:
        return "unattributed", ["Candidate full name tokens not completely matched"]

    evidence: List[str] = [f"Full name '{name}' matched in public record"]
    signals = 0

    # +1 signal: Location / City
    if location:
        loc_parts = [p.strip().lower() for p in re.split(r"[,/]", location) if len(p.strip()) >= 3]
        for part in loc_parts:
            part_tokens = [t for t in part.split() if len(t) >= 3]
            if part_tokens and all(re.search(r"\b" + re.escape(ct) + r"\b", blob) for ct in part_tokens):
                signals += 1
                evidence.append(f"Location signal: '{part}' matches candidate location")
                break

    # +1 signal: Any claimed employer
    if employers:
        for emp in employers:
            emp_clean = emp.strip().lower()
            if len(emp_clean) >= 3 and emp_clean in blob:
                signals += 1
                evidence.append(f"Employer signal: '{emp}' matches claimed work history")
                break

    # +1 signal: Candidate email / handle
    if email and "@" in email:
        email_clean = email.strip().lower()
        handle = email_clean.split("@")[0]
        if email_clean in blob:
            signals += 1
            evidence.append("Email signal: Candidate email address explicitly cited")
        elif len(handle) >= 4 and re.search(r"\b" + re.escape(handle) + r"\b", blob):
            signals += 1
            evidence.append(f"Handle signal: Email prefix '{handle}' matches profile handle")

    if signals >= 1:
        return "attributed", evidence

    return "unattributed", ["Full name matched but lacks corroborating employer, location, or email signal"]


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

    # 5b. Handle-derived searches (email prefix + supplied handles).
    #     `derive_handles_from_email` previously existed but was never called.
    handle_terms = []
    for h in derive_handles_from_email(email):
        if h and len(h) >= 3:
            handle_terms.append(h)
    for h in (additional_handles or []):
        h = (h or "").strip().lstrip("@")
        if h and len(h) >= 3 and h not in handle_terms:
            handle_terms.append(h)
    for idx, h in enumerate(handle_terms[:3]):
        queries[f"handle_{idx}"] = {
            "target": f"Handle: {h}",
            "query": f'"{h}" {loc}'.strip(),
        }

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
        "raw_findings": [],
        "attributed": [],
        "unattributed": [],
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
                        # Candidate-focused finding: run Entity Resolution Gate
                        attr_status, attr_evidence = attribute_result(
                            result=entry,
                            name=c_name,
                            location=loc,
                            employers=past_employers or [],
                            email=email or "",
                        )
                        entry["attribution_status"] = attr_status
                        entry["attribution_evidence"] = attr_evidence

                        if attr_status == "attributed":
                            search_results["attributed"].append(entry)
                            if classified:
                                if classified["category"] == "Professional":
                                    search_results["professional"].append(entry)
                                elif classified["category"] == "Social":
                                    search_results["social"].append(entry)
                                elif classified["category"] == "Publications":
                                    search_results["web_mentions"].append(entry)
                            else:
                                search_results["web_mentions"].append(entry)
                        else:
                            search_results["unattributed"].append(entry)

                    search_results["raw_findings"].append({
                        "target": target,
                        "category": (classified or {}).get("category", target),
                        "platform": entry.get("platform", target),
                        "title": item["title"],
                        "url": url,
                        "snippet": item["body"],
                        "attribution_status": entry.get("attribution_status", "unattributed")
                    })
            except Exception:
                pass

    return search_results

"""
Candidate Resume Parser & Entity Extractor
Extracts text from PDF, DOCX, and TXT files, then structures all candidate data
into clean JSON via Gemini (with heuristic fallback if API key is not yet set).
"""

import io
import json
import os
import re
from typing import Dict, Any, Optional
import pypdf
import docx


def extract_raw_text(file_bytes: bytes, filename: str) -> str:
    """Extract raw text from uploaded PDF, DOCX, or TXT file."""
    lower_name = filename.lower()
    text = ""
    try:
        if lower_name.endswith(".pdf"):
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        elif lower_name.endswith(".docx"):
            doc = docx.Document(io.BytesIO(file_bytes))
            for para in doc.paragraphs:
                if para.text:
                    text += para.text + "\n"
        elif lower_name.endswith(".txt"):
            text = file_bytes.decode("utf-8", errors="ignore")
        else:
            # Attempt plain text decoding as fallback
            text = file_bytes.decode("utf-8", errors="ignore")
    except Exception as e:
        text = f"Error reading file {filename}: {str(e)}"
    return text.strip()


def heuristic_parse_resume(raw_text: str) -> Dict[str, Any]:
    """Fallback heuristic parser if Gemini API key is unavailable."""
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    
    # Simple email & phone regex
    email_match = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", raw_text)
    phone_match = re.search(r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", raw_text)
    
    # Candidate name usually first non-empty line
    candidate_name = lines[0] if lines else "Unknown Candidate"
    if len(candidate_name) > 40:
        candidate_name = candidate_name[:40]

    # Find URLs / handles
    links = []
    url_matches = re.findall(r"https?://[^\s]+|(?:linkedin\.com|github\.com|twitter\.com|x\.com)/[^\s]+", raw_text)
    for u in set(url_matches):
        links.append({"platform": "Web", "url_or_handle": u})

    return {
        "candidate_name": candidate_name,
        "email": email_match.group(0) if email_match else "",
        "phone": phone_match.group(0) if phone_match else "",
        "location": "",
        "target_role": "Store Associate",
        "summary": "Parsed via offline fallback mode.",
        "work_history": [],
        "education": [],
        "references": [],
        "links_and_handles": links,
        "raw_text": raw_text
    }


def call_gemini_parser(raw_text: str, api_key: str) -> Dict[str, Any]:
    """Call Gemini to extract structured JSON from raw resume text."""
    prompt = f"""
You are an expert HR assistant. Extract structured candidate details from the following resume text into a single, valid JSON object.

Strict Rules:
- Return ONLY valid JSON, with NO surrounding markdown backticks (no ```json ... ```).
- If a field is unknown, use an empty string or empty list.
- Format dates consistently (e.g. "2021-05" or "May 2021" or "Present").
- Include any references explicitly listed, with their contact and claimed company if available.
- Include social media URLs or handles found on the resume.

JSON Schema:
{{
  "candidate_name": "Full Name",
  "email": "candidate@example.com",
  "phone": "555-123-4567",
  "location": "City, State",
  "target_role": "Title or recent role",
  "summary": "Brief 1-2 sentence career profile",
  "work_history": [
    {{
      "company": "Store or Company Name",
      "title": "Job Title",
      "start_date": "Date",
      "end_date": "Date or Present",
      "location": "City, State",
      "key_responsibilities": ["duty 1", "duty 2"]
    }}
  ],
  "education": [
    {{
      "institution": "School or University Name",
      "degree": "Degree or Diploma",
      "graduation_year": "Year"
    }}
  ],
  "references": [
    {{
      "name": "Reference Full Name",
      "title": "Their Title",
      "company": "Company Name",
      "phone": "Phone or empty",
      "email": "Email or empty",
      "relationship": "Former Manager / Colleague / etc."
    }}
  ],
  "links_and_handles": [
    {{
      "platform": "LinkedIn / GitHub / Twitter / Portfolio",
      "url_or_handle": "URL or @handle"
    }}
  ]
}}

Resume Text:
\"\"\"
{raw_text[:12000]}
\"\"\"
"""
    # 1. Try modern google-genai SDK
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        for mod in ["gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash"]:
            try:
                response = client.models.generate_content(
                    model=mod,
                    contents=prompt,
                )
                content = response.text.strip()
                if content.startswith("```"):
                    content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
                    content = re.sub(r"\n?```$", "", content)
                data = json.loads(content)
                data["raw_text"] = raw_text
                data["_model_used"] = mod
                return data
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
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                res_json = resp.json()
                text_part = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text_part.startswith("```"):
                    text_part = re.sub(r"^```[a-zA-Z]*\n?", "", text_part)
                    text_part = re.sub(r"\n?```$", "", text_part)
                data = json.loads(text_part)
                data["raw_text"] = raw_text
                data["_model_used"] = "gemini-2.5-flash (REST)"
                return data
    except Exception:
        pass

    # Fallback to heuristic
    parsed = heuristic_parse_resume(raw_text)
    parsed["error"] = "Gemini API parsing failed or API key was invalid. Loaded heuristic fields."
    return parsed


def parse_candidate_document(file_bytes: bytes, filename: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """Top-level document parser returning structured candidate dictionary."""
    raw_text = extract_raw_text(file_bytes, filename)
    if not raw_text or len(raw_text.strip()) < 10:
        return {
            "candidate_name": "",
            "email": "",
            "phone": "",
            "location": "",
            "target_role": "",
            "summary": "Could not extract text from the uploaded file.",
            "work_history": [],
            "education": [],
            "references": [],
            "links_and_handles": [],
            "raw_text": raw_text,
            "error": "No readable text detected in file."
        }
    
    if api_key and api_key.strip():
        return call_gemini_parser(raw_text, api_key.strip())
    else:
        return heuristic_parse_resume(raw_text)

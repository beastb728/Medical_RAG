import json
import requests
import os
import re

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = "mistral"   # fast + good at structured extraction


# -------------------------
# helpers
# -------------------------
def normalize_test_name(name: str) -> str:
    """
    Light, non-semantic normalization.
    Removes formatting noise only.
    """
    name = name.lower()
    name = re.sub(r"\s+", " ", name)
    name = name.replace(" ,", ",")
    name = name.replace(", ", ",")
    return name.strip()


# -------------------------
# test extraction
# -------------------------
def extract_tests_from_page(page_text: str) -> list[dict]:
    """
    Extract clinically reported test results from ONE PAGE of a medical report.
    Returns a list of tests. If no tests found, returns empty list.
    """

    prompt = f"""
You are a medical laboratory report parser.

You will be given the text of ONE PAGE of a medical lab report.

Your task is to extract ONLY clinically reported laboratory test results.

A laboratory test result MUST include:
- a test name
- a measured value (numeric or qualitative like Negative/Absent)
- optionally a unit
- optionally a reference range

You MUST ALSO determine a test_context for each test.

test_context means:
- the panel, section, or sample type the test belongs to

Use the nearest section heading or panel name on the page.
If the context is unclear, use an empty string.

You MUST IGNORE:
- lab names, package names, branding
- section headings without results
- reference-only ranges (e.g. trimester ranges)
- guidelines, explanations, comments, notes
- repeated patient information
- page numbers or table headers
- educational or descriptive paragraphs

Rules:
- Do NOT infer or guess values
- Do NOT include ranges without an actual measured result
- If the page has no valid test results, return an empty list
- Output JSON ONLY, no explanations

Additional rule for reference ranges:
- If a numeric range (e.g. 0.80-2.0, 6.09 - 12.23) appears on the SAME LINE
  as the measured value or immediately adjacent to it, treat it as
  the reference_range.
- Do NOT extract ranges that appear in guidelines, trimester tables,
  explanatory text, or standalone reference sections.

Additional clarification:
- Calculated or derived tests are valid if they include a measured value.
- Do NOT exclude a test solely because it appears at the end of a section.

Output format:
{{
  "tests": [
    {{
      "test_name": "",
      "test_context": "",
      "value": "",
      "unit": "",
      "reference_range": ""
    }}
  ]
}}

Page text:
{page_text}
"""

    try:
        res = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False
            },
            timeout=300
        )
    except requests.exceptions.RequestException:
        return []

    raw = res.json().get("response", "").strip()

    try:
        parsed = json.loads(raw)
        tests = parsed.get("tests", [])

        # light normalization only
        for t in tests:
            if t.get("test_name"):
                t["test_name"] = normalize_test_name(t["test_name"])

        return tests
    except Exception:
        # fail safely, never crash the app
        return []


# -------------------------
# patient info extraction
# -------------------------
def extract_patient_info(text: str) -> dict:
    """
    Extract patient name and report date from full document text.
    """

    name = re.search(
        r"Patient Name\s*:\s*(?:Mr\.?|Ms\.?|Mrs\.?)?\s*([A-Z\s]+)",
        text,
        re.I
    )

    date = re.search(
        r"Reporting On\s*:\s*([\d]{2}[\/\-][A-Za-z]{3}[\/\-]\d{4})",
        text,
        re.I
    )

    return {
        "patient_name": name.group(1).strip().lower() if name else None,
        "report_date": date.group(1) if date else None
    }

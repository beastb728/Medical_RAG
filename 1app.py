import streamlit as st
from PyPDF2 import PdfReader
import pandas as pd
import re
import requests
import json
import os

from medical_extractor import (
    extract_tests_from_page,
    extract_patient_info
)

from medical_db import (
    init_db,
    get_or_create_patient,
    insert_report,
    insert_test_results,
    get_connection
)

# -------------------------
# ollama config
# -------------------------
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = "mistral"
MATCH_CONFIDENCE_THRESHOLD = 0.9

# -------------------------
# page config
# -------------------------
st.set_page_config(page_title="medicalrag", layout="wide")
st.title("medicalrag – medical records system")

# -------------------------
# init database
# -------------------------
init_db()

# -------------------------
# helpers
# -------------------------

def classify_test_type(test_name: str, unit: str) -> str:
    name = test_name.lower()
    if "/" in name or unit.lower() == "ratio":
        return "ratio"
    return "concentration"


def extract_panel(test_name: str) -> str:
    n = test_name.lower()

    if any(x in n for x in ["thyroid", "tsh", "t3", "t4"]):
        return "thyroid"

    if any(x in n for x in ["cholesterol", "triglyceride", "hdl", "ldl", "vldl", "lipid"]):
        return "lipid"

    if "bilirubin" in n or "liver" in n:
        return "liver"

    return "unknown"


def recover_ranges_from_text(page_text: str):
    recovered = {}
    lines = [l.strip() for l in page_text.splitlines() if l.strip()]
    current_test = None

    for line in lines:
        if (
            len(line) > 8
            and line.isupper()
            and not any(x in line for x in ["METHOD", "PROFILE"])
        ):
            current_test = line.lower()
            continue

        if not current_test:
            continue

        unit_match = re.search(
            r"(mg/dl|mg/dL|ug/dL|ng/ml|uIU/mL|Ratio)",
            line,
            re.I
        )
        unit = unit_match.group(1).lower() if unit_match else ""

        m = re.search(r"(\d+(\.\d+)?)\s*[-–]\s*(\d+(\.\d+)?)", line)
        if m:
            recovered[(current_test, unit)] = m.group(0)
            continue

        limit = re.search(r"(upto|<|≤)\s*(\d+(\.\d+)?)", line, re.I)
        if limit:
            recovered[(current_test, unit)] = f"{limit.group(1)} {limit.group(2)}"

    return recovered


def get_existing_tests_for_patient(patient_name):
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT test_name, unit
        FROM test_results t
        JOIN reports r ON t.report_id = r.report_id
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE p.name = ?
    """, (patient_name,)).fetchall()
    conn.close()

    tests = []
    for name, unit in rows:
        tests.append({
            "name": name,
            "unit": unit,
            "type": classify_test_type(name, unit),
            "panel": extract_panel(name)
        })
    return tests


def ai_match_test_name(new_test, existing_tests):
    if not existing_tests:
        return None

    candidates = "\n".join(f"- {t['name']}" for t in existing_tests)

    prompt = f"""
You are a medical lab test name matcher.

Rules:
- Match ONLY if it is the same lab test.
- Ratios are NOT the same as base measurements.
- If unsure, return no_match.
- Output JSON only.

NEW TEST:
{new_test['name']}

EXISTING TESTS:
{candidates}

Output:
{{
  "match": "<existing test name or no_match>",
  "confidence": 0.0
}}
"""

    try:
        res = requests.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120
        )
        out = json.loads(res.json()["response"])
    except Exception:
        return None

    if (
        out.get("match")
        and out["match"] != "no_match"
        and float(out.get("confidence", 0)) >= MATCH_CONFIDENCE_THRESHOLD
    ):
        return out["match"]

    return None

# -------------------------
# upload section
# -------------------------
st.header("upload medical report")

uploaded = st.file_uploader("upload pdf medical report", type=["pdf"])

if uploaded:
    reader = PdfReader(uploaded)

    if st.button("read this document"):
        st.session_state["full_text"] = "\n".join(
            page.extract_text() or "" for page in reader.pages
        )

    full_text = st.session_state.get("full_text")

    if full_text:
        st.text_area("extracted text preview", full_text[:3000], height=300)

    if st.button("add this document to records"):
        with st.spinner("processing medical report…"):
            patient_info = extract_patient_info(full_text)

            if not patient_info.get("patient_name"):
                st.error("could not detect patient name from report")
                st.stop()

            patient_id = get_or_create_patient(patient_info["patient_name"])


            report_id = insert_report(patient_id, patient_info.get("report_date"), uploaded.name)

            all_tests = []
            range_cache = {}

            for page in reader.pages:
                text = page.extract_text()
                if not text:
                    continue

                page_tests = extract_tests_from_page(text)
                recovered = recover_ranges_from_text(text)

                for t in page_tests:
                    key = ((t["test_name"] or "").lower(), (t.get("unit") or "").lower())
                    if t.get("reference_range"):
                        range_cache[key] = t["reference_range"]
                    elif key in recovered:
                        range_cache[key] = recovered[key]

                all_tests.extend(page_tests or [])

            for t in all_tests:
                key = ((t["test_name"] or "").lower(), (t.get("unit") or "").lower())
                if not t.get("reference_range") and key in range_cache:
                    t["reference_range"] = range_cache[key]

            # -------- AI identity resolution --------
            existing_tests = get_existing_tests_for_patient(patient_info["patient_name"])

            for t in all_tests:
                new_test = {
                    "name": t["test_name"],
                    "unit": t.get("unit", ""),
                    "type": classify_test_type(t["test_name"], t.get("unit", "")),
                    "panel": extract_panel(t["test_name"])
                }

                candidates = [
                    et for et in existing_tests
                    if et["type"] == new_test["type"]
                    and et["panel"] == new_test["panel"]
                    and et["unit"].lower() == new_test["unit"].lower()
                ]

                matched = ai_match_test_name(new_test, candidates)
                if matched:
                    t["test_name"] = matched

            insert_test_results(report_id, all_tests)

        st.success("medical report added successfully")

# -------------------------
# view section (unchanged)
# -------------------------
st.header("view patient records")
# -------------------------
# patient selector
# -------------------------
conn = get_connection()
patients = conn.execute(
    "SELECT name FROM patients ORDER BY name"
).fetchall()
conn.close()

patient_names = [p[0] for p in patients if p[0]]

if not patient_names:
    st.info("no patients found yet")
    st.stop()

selected_patient = st.selectbox(
    "select patient",
    patient_names
)

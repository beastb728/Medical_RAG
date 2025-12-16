import streamlit as st
import sqlite3
import requests
import os

from medical_db import (
    get_test_explanation,
    save_test_explanation,
    clear_test_explanations
)

# -------------------------
# config
# -------------------------
DB_PATH = "medical_records.db"
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MODEL = "llama3"

# -------------------------
# helpers
# -------------------------
def get_connection():
    return sqlite3.connect(DB_PATH)


def get_patients():
    conn = get_connection()
    rows = conn.execute("SELECT name FROM patients").fetchall()
    conn.close()
    return [r[0] for r in rows]


def parse_value(value):
    if value is None:
        return None
    try:
        return float(str(value).replace("H", "").replace("L", "").strip())
    except Exception:
        return None


def get_abnormal_type(raw_value, normal_range):
    value = parse_value(raw_value)
    if value is None or not normal_range:
        return None

    try:
        rng = normal_range.lower().replace(" ", "")

        if "-" in rng:
            low, high = rng.split("-")
            if value < float(low):
                return "low"
            if value > float(high):
                return "high"

        if "upto" in rng or rng.startswith("<"):
            limit = float(rng.replace("upto", "").replace("<", ""))
            if value > limit:
                return "high"

        if "morethan" in rng or rng.startswith(">"):
            limit = float(rng.replace("morethan", "").replace(">", ""))
            if value < limit:
                return "low"

    except Exception:
        return None

    return None


def get_problem_tests(patient_name):
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            t.test_name,
            t.test_context,
            t.value,
            t.unit,
            t.normal_range,
            r.report_date
        FROM test_results t
        JOIN reports r ON t.report_id = r.report_id
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE p.name = ?
        ORDER BY r.report_date DESC
    """, (patient_name,)).fetchall()
    conn.close()

    problems = []
    for test, context, value, unit, rng, date in rows:
        abnormal_type = get_abnormal_type(value, rng)
        if abnormal_type:
            problems.append(
                (test, context, value, unit, rng, date, abnormal_type)
            )

    return problems


# -------------------------
# AI explanation
# -------------------------
def generate_test_explanation(test_name, test_context, abnormal_type):
    prompt = f"""
You are a medical reference system.

Rules:
- bullet points only
- extremely short
- no diagnosis
- no treatment advice
- no personalization

Format exactly:

"{test_name} ({test_context})":
- what this test measures

"{abnormal_type} value may be seen when":
- 1–2 short bullets

"notes":
- 1 short bullet if relevant
"""

    res = requests.post(
        f"{OLLAMA_HOST}/api/generate",
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False
        },
        timeout=120
    )

    return res.json().get("response", "").strip()


# -------------------------
# UI
# -------------------------
st.set_page_config(page_title="problems", layout="wide")
st.title("medical issues detected")

if st.button("reset ai explanations"):
    clear_test_explanations()
    st.success("all ai explanations cleared")
    st.rerun()


patients = get_patients()

if not patients:
    st.info("no patient data found. upload a report first.")
    st.stop()

patient = st.selectbox("select patient", patients)

problems = get_problem_tests(patient)

if not problems:
    st.success("no issues found. all values are within range.")
    st.stop()

st.subheader(f"issues found: {len(problems)}")

cols = st.columns(2)

for idx, (test, context, value, unit, rng, date, abnormal_type) in enumerate(problems):
    display_name = f"{test} ({context})" if context else test

    with cols[idx % 2]:
        st.markdown(
            f"""
            <div style="
                border:1px solid #ddd;
                border-radius:10px;
                padding:14px;
                margin-bottom:14px;
                background-color:#fafafa;
            ">
                <h4>Issue {idx+1}</h4>
                <b>Test:</b> {display_name}<br>
                <b>Issue:</b> {abnormal_type}<br>
                <b>Your value:</b> {value} {unit}<br>
                <b>Expected range:</b> {rng}<br>
                <b>Report date:</b> {date}
            </div>
            """,
            unsafe_allow_html=True
        )

        with st.expander("understanding this finding"):
            explanation = get_test_explanation(
                test,
                context,
                abnormal_type
            )

            if explanation:
                st.write(explanation)
            else:
                if st.button(
                    f"generate explanation for {display_name}",
                    key=f"explain-{idx}"
                ):
                    with st.spinner("generating explanation…"):
                        explanation = generate_test_explanation(
                            test,
                            context,
                            abnormal_type
                        )
                        save_test_explanation(
                            test,
                            context,
                            abnormal_type,
                            explanation
                        )
                    st.write(explanation)

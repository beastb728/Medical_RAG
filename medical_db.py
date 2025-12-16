import sqlite3

DB_PATH = "medical_records.db"


def get_connection():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # -------------------------
    # core entities
    # -------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS patients (
        patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        report_id INTEGER PRIMARY KEY AUTOINCREMENT,
        patient_id INTEGER,
        report_date TEXT,
        source_file TEXT,
        FOREIGN KEY(patient_id) REFERENCES patients(patient_id)
    )
    """)

    # -------------------------
    # test results (NOW CANONICAL-AWARE)
    # -------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS test_results (
        result_id INTEGER PRIMARY KEY AUTOINCREMENT,
        report_id INTEGER,
        canonical_id TEXT,
        test_name TEXT,
        test_context TEXT,
        value TEXT,
        unit TEXT,
        normal_range TEXT,
        FOREIGN KEY(report_id) REFERENCES reports(report_id),
        FOREIGN KEY(canonical_id) REFERENCES canonical_tests(canonical_id)
    )
    """)

    # -------------------------
    # canonical test registry
    # -------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS canonical_tests (
        canonical_id TEXT PRIMARY KEY,
        canonical_name TEXT,
        unit TEXT,
        panel TEXT
    )
    """)

    # -------------------------
    # explanations (context-aware)
    # -------------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS test_explanations (
        test_name TEXT,
        test_context TEXT,
        abnormal_type TEXT,
        explanation TEXT,
        PRIMARY KEY (test_name, test_context, abnormal_type)
    )
    """)

    conn.commit()
    conn.close()


# -------------------------
# patients & reports
# -------------------------
def get_or_create_patient(name):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT patient_id FROM patients WHERE name = ?",
        (name,)
    )
    row = cur.fetchone()

    if row:
        patient_id = row[0]
    else:
        cur.execute(
            "INSERT INTO patients (name) VALUES (?)",
            (name,)
        )
        patient_id = cur.lastrowid

    conn.commit()
    conn.close()
    return patient_id


def insert_report(patient_id, report_date, source_file):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    INSERT INTO reports (patient_id, report_date, source_file)
    VALUES (?, ?, ?)
    """, (patient_id, report_date, source_file))

    report_id = cur.lastrowid
    conn.commit()
    conn.close()
    return report_id


# -------------------------
# test results
# -------------------------
def insert_test_results(report_id, tests):
    conn = get_connection()
    cur = conn.cursor()

    for t in tests:
        canonical_id = t.get("canonical_id")

        test_name = (t.get("test_name") or "").strip().lower()
        test_context = (t.get("test_context") or "").strip().lower()
        value = str(t.get("value") or "").strip()
        unit = str(t.get("unit") or "").strip()
        normal_range = (
            t.get("reference_range")
            or t.get("normal_range")
            or ""
        ).strip()

        if not test_name or not value:
            continue

        cur.execute("""
        INSERT INTO test_results
        (report_id, canonical_id, test_name, test_context, value, unit, normal_range)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id,
            canonical_id,
            test_name,
            test_context,
            value,
            unit,
            normal_range
        ))

    conn.commit()
    conn.close()


# -------------------------
# canonical tests helpers
# -------------------------
def upsert_canonical_test(canonical_id, canonical_name, unit=None, panel=None):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO canonical_tests
        (canonical_id, canonical_name, unit, panel)
        VALUES (?, ?, ?, ?)
    """, (
        canonical_id,
        canonical_name,
        unit,
        panel
    ))
    conn.commit()
    conn.close()


def get_all_canonical_tests():
    conn = get_connection()
    rows = conn.execute("""
        SELECT canonical_id, canonical_name, unit, panel
        FROM canonical_tests
    """).fetchall()
    conn.close()
    return rows


# -------------------------
# explanations (context-aware)
# -------------------------
def get_test_explanation(test_name, test_context, abnormal_type):
    conn = get_connection()
    row = conn.execute("""
        SELECT explanation
        FROM test_explanations
        WHERE test_name = ?
          AND test_context = ?
          AND abnormal_type = ?
    """, (
        test_name.lower(),
        test_context.lower(),
        abnormal_type
    )).fetchone()
    conn.close()
    return row[0] if row else None


def save_test_explanation(test_name, test_context, abnormal_type, explanation):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO test_explanations
        (test_name, test_context, abnormal_type, explanation)
        VALUES (?, ?, ?, ?)
    """, (
        test_name.lower(),
        test_context.lower(),
        abnormal_type,
        explanation
    ))
    conn.commit()
    conn.close()


def clear_test_explanations():
    conn = get_connection()
    conn.execute("DELETE FROM test_explanations")
    conn.commit()
    conn.close()
#
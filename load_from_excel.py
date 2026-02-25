

import os, re, sys, sqlite3

try:
    import pandas as pd
except ImportError:
    print("pandas not installed. Run: pip install pandas openpyxl")
    sys.exit(1)

OLD_EXCEL = "GST_dataset_for_MCP.xlsx"
NEW_EXCEL = "GST_CGST_Rates_Clean.xlsx"
DB_PATH   = "gst_data.db"

VALID_IGST = {0.0, 0.25, 0.5, 1.5, 3.0, 5.0, 18.0, 28.0, 40.0}

CESS_HSN_PREFIXES = {
    "2202", "2401", "2402", "2403", "2404", "2106",
    "8703", "8711", "8704",
}


def parse_hsn_raw(raw) -> list:
    if pd.isna(raw):
        return []
    text = str(raw).strip()
    if not text:
        return []

    # Strip exceptions and qualifiers
    text = re.sub(r'\[Except[^\]]*\]',    '', text, flags=re.I)
    text = re.sub(r'\[other than[^\]]*\]','', text, flags=re.I)
    text = re.sub(r'\(Except[^)]*\)',      '', text, flags=re.I)
    text = re.sub(r'\(other than[^)]*\)',  '', text, flags=re.I)
    text = re.sub(r'\bany\s+(?:other\s+)?chapter\b', '', text, flags=re.I)
    text = re.sub(r'\bSS\s*', '', text)

    # Normalize OR -> comma
    text = re.sub(r'\bor\b', ',', text, flags=re.I)

    codes = []
    for part in text.split(','):
        part = part.strip().replace(' ', '')
        if re.match(r'^\d{2,}$', part):
            codes.append(part)
    return codes


def has_cess(hsn_code: str) -> int:
    return 1 if any(hsn_code.startswith(p) for p in CESS_HSN_PREFIXES) else 0


def infer_level(hsn_code: str) -> str:
    n = len(hsn_code)
    if n <= 2:   return "chapter"
    if n <= 4:   return "heading"
    if n <= 6:   return "subheading"
    return "tariff_item"


def load_old_excel(path):
    print(f"Reading {path}...")
    sheets  = pd.read_excel(path, sheet_name=["gst_rate_lines", "gst_hsn_map"])
    lines   = sheets["gst_rate_lines"]
    hsn_map = sheets["gst_hsn_map"]

    print(f"  gst_rate_lines: {len(lines)} rows")
    print(f"  gst_hsn_map:    {len(hsn_map)} rows")

    lines["igst_rate_percent"] = pd.to_numeric(lines["igst_rate_percent"], errors="coerce").fillna(0.0)
    valid   = lines[lines["igst_rate_percent"].isin(VALID_IGST)].copy()
    skipped = len(lines) - len(valid)
    print(f"  Valid rate lines: {len(valid)}  ({skipped} cess/invalid skipped)")

    # Drop NIL-contaminated Schedule VII rows
    nil_in_s7 = valid[
        (valid["schedule"] == "VII") &
        (valid["description"].str.contains(r'\bNIL\b|\bNil\b', na=False, regex=True))
    ]
    if len(nil_in_s7):
        print(f"  Dropping {len(nil_in_s7)} NIL-contaminated Schedule VII rows")
        valid = valid[~valid.index.isin(nil_in_s7.index)]

    valid["line_id"] = valid["line_id"].astype(str)
    line_lookup = valid.set_index("line_id")[
        ["igst_rate_percent", "description", "schedule", "hsn_raw"]
    ].to_dict("index")

    rows, seen = [], set()
    fixed_or = used_map = 0

    for lid, info in line_lookup.items():
        codes = parse_hsn_raw(info["hsn_raw"])

        if not codes:
            map_codes = hsn_map[hsn_map["line_id"].astype(str) == lid]["hsn_code"].tolist()
            codes = [str(c).strip() for c in map_codes if c]
            used_map += 1

        if re.search(r'\bor\b', str(info["hsn_raw"]), re.I) and codes:
            fixed_or += 1

        for hsn in codes:
            key = (lid, hsn)
            if key in seen: continue
            seen.add(key)
            desc = str(info["description"]).strip() if pd.notna(info["description"]) else ""
            rows.append({
                "line_id":  int(lid),
                "hsn_code": hsn,
                "desc":     desc,
                "igst":     float(info["igst_rate_percent"]),
                "schedule": str(info["schedule"]).strip() if pd.notna(info["schedule"]) else "",
                "category": "Services" if hsn.startswith("99") else "Goods",
                "has_cess": has_cess(hsn),
                "hsn_level": infer_level(hsn),
            })

    print(f"  OR rows re-parsed: {fixed_or}")
    print(f"  Map fallbacks:     {used_map}")
    print(f"  Rows to insert:    {len(rows)}")
    return rows


def merge_hsn_level(rows, new_excel_path):
    if not os.path.exists(new_excel_path):
        print(f"  (Skipping hsn_level merge — {new_excel_path} not found)")
        return rows

    print(f"\nMerging hsn_level from {new_excel_path}...")
    new = pd.read_excel(new_excel_path, sheet_name="GST_Rates")
    new["hsn_code"] = new["hsn_code"].astype(str).str.strip()

    level_map = (
        new.dropna(subset=["hsn_code", "hsn_level"])
           .drop_duplicates(subset=["hsn_code"])
           .set_index("hsn_code")["hsn_level"]
           .to_dict()
    )

    merged = 0
    for row in rows:
        lvl = level_map.get(row["hsn_code"])
        if lvl:
            row["hsn_level"] = str(lvl)
            merged += 1

    print(f"  Levels merged: {merged}/{len(rows)}")
    return rows


def write_db(rows):
    conn   = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("DROP TABLE IF EXISTS hsn_data")
    cursor.execute("""
        CREATE TABLE hsn_data (
            line_id     INTEGER  NOT NULL,
            hsn_code    TEXT     NOT NULL,
            description TEXT     NOT NULL,
            gst_rate    REAL     NOT NULL DEFAULT 0,
            cess        REAL     NOT NULL DEFAULT 0,
            has_cess    INTEGER  NOT NULL DEFAULT 0,
            category    TEXT     NOT NULL DEFAULT 'Goods',
            schedule    TEXT,
            hsn_level   TEXT,
            PRIMARY KEY (line_id, hsn_code)
        )
    """)
    for sql in [
        "CREATE INDEX IF NOT EXISTS idx_hsn   ON hsn_data(hsn_code)",
        "CREATE INDEX IF NOT EXISTS idx_desc  ON hsn_data(description)",
        "CREATE INDEX IF NOT EXISTS idx_rate  ON hsn_data(gst_rate)",
        "CREATE INDEX IF NOT EXISTS idx_sched ON hsn_data(schedule)",
    ]:
        cursor.execute(sql)

    cursor.executemany(
        """INSERT OR IGNORE INTO hsn_data
           (line_id, hsn_code, description, gst_rate, cess, has_cess, category, schedule, hsn_level)
           VALUES (:line_id, :hsn_code, :desc, :igst, 0.0, :has_cess, :category, :schedule, :hsn_level)""",
        rows,
    )

    conn.commit()
    inserted = cursor.execute("SELECT COUNT(*) FROM hsn_data").fetchone()[0]
    conn.close()
    return inserted


SPOT_CHECKS = [
    ("0901",    "Coffee (roasted, 5%)",        5.0),
    ("0901",    "Coffee beans (raw, NIL)",      0.0),
    ("7108",    "Gold",                        3.0),
    ("7102",    "Rough diamonds",              0.25),
    ("7102",    "Cut/polished diamonds",       1.5),
    ("8517",    "Smartphones",                18.0),
    ("3004",    "Medicines",                   5.0),
    ("870321",  "Petrol car <=1200cc",        18.0),
    ("870322",  "Petrol car 1200-1500cc",     18.0),
    ("8703",    "Luxury cars",                40.0),
    ("8711",    "Motorcycles <=350cc",        18.0),
    ("8711",    "Motorcycles >350cc",         40.0),
    ("2402",    "Cigarettes",                 28.0),
    ("220210",  "Aerated drinks",             40.0),
    ("9302",    "Revolvers",                  40.0),
    # NIL entries (stored without leading zeros)
    ("0101",    "Live asses (NIL)",            0.0),
    ("4901",    "Books (NIL)",                 0.0),
    ("0701",    "Fresh potatoes (NIL)",        0.0),
    # OR-fixed entries
    ("1404",    "Mehendi (OR fix)",            5.0),
    ("3305",    "Hair products (OR fix)",     18.0),
    ("6309",    "Worn clothing (OR fix)",      5.0),
    ("6310",    "Rags (OR fix)",               5.0),
    ("8802",    "Personal aircraft (OR fix)", 40.0),
    ("8806",    "Drones/unmanned (OR fix)",    5.0),  # unmanned aircraft = Schedule I
]


def verify():
    conn     = sqlite3.connect(DB_PATH)
    all_pass = True
    print("\nSpot checks:")

    for hsn, label, expected in SPOT_CHECKS:
        row = conn.execute(
            "SELECT hsn_code, gst_rate, has_cess, description FROM hsn_data "
            "WHERE hsn_code = ? AND ABS(gst_rate - ?) < 0.01 LIMIT 1",
            (hsn, expected),
        ).fetchone()

        if row:
            cess_flag = " [cess]" if row[2] else ""
            print(f"  ✓ {label:<32} HSN {row[0]:<12} {row[1]:5.2f}%{cess_flag}  {str(row[3])[:35]}")
        else:
            all_pass = False
            print(f"  ✗ {label:<32} NOT FOUND at {expected}%  (HSN {hsn})")

    conn.close()
    return all_pass


def print_summary():
    conn = sqlite3.connect(DB_PATH)
    total      = conn.execute("SELECT COUNT(*) FROM hsn_data").fetchone()[0]
    unique_hsn = conn.execute("SELECT COUNT(DISTINCT hsn_code) FROM hsn_data").fetchone()[0]
    multi      = conn.execute(
        "SELECT COUNT(*) FROM (SELECT hsn_code FROM hsn_data GROUP BY hsn_code HAVING COUNT(DISTINCT gst_rate) > 1)"
    ).fetchone()[0]
    cess_ct    = conn.execute("SELECT COUNT(*) FROM hsn_data WHERE has_cess=1").fetchone()[0]
    nil_ct     = conn.execute("SELECT COUNT(*) FROM hsn_data WHERE gst_rate=0").fetchone()[0]
    dist       = conn.execute("SELECT gst_rate, COUNT(*) FROM hsn_data GROUP BY gst_rate ORDER BY gst_rate").fetchall()
    levels     = conn.execute("SELECT hsn_level, COUNT(*) FROM hsn_data GROUP BY hsn_level ORDER BY COUNT(*) DESC").fetchall()
    conn.close()

    print(f"\nTotal rows:           {total}")
    print(f"Unique HSN codes:     {unique_hsn}")
    print(f"Multi-rate HSN codes: {multi}")
    print(f"NIL/exempt entries:   {nil_ct}")
    print(f"Cess-flagged entries: {cess_ct}")
    print("\nRate distribution:")
    for rate, count in dist:
        bar = "█" * min(count // 10, 50)
        print(f"  {rate:6.3f}%  {count:4d}  {bar}")
    print("\nHSN level distribution:")
    for level, count in levels:
        print(f"  {str(level):<15} {count}")


def main():
    print("=" * 58)
    print("GST Excel Loader  (v2 — robust parsing)")
    print("Source: Notification 09/2025-CT(Rate), 22 Sept 2025")
    print("=" * 58)
    print()

    if not os.path.exists(OLD_EXCEL):
        print(f"'{OLD_EXCEL}' not found.")
        sys.exit(1)

    rows = load_old_excel(OLD_EXCEL)
    if len(rows) < 200:
        print(f"Only {len(rows)} rows — something went wrong.")
        sys.exit(1)

    rows = merge_hsn_level(rows, NEW_EXCEL)

    if os.path.exists(DB_PATH):
        ans = input(f"\nReplace existing '{DB_PATH}'? (y/n): ").strip().lower()
        if ans != "y":
            print("Cancelled.")
            return

    inserted = write_db(rows)
    print(f"\n✓  Loaded {inserted} rows into {DB_PATH}")

    print_summary()
    ok = verify()

    if ok:
        print("\nAll spot checks passed — database is ready!")
        print("    Next step:  python server.py")
    else:
        print("\n⚠   Some checks failed — review above.")


if __name__ == "__main__":
    main()
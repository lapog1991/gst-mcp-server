"""
setup_db.py
-----------
Run this ONCE to build your local GST database from CBIC data.
Downloads the official HSN master from the GST portal and loads into SQLite.

Usage:
    python setup_db.py

If the download fails (CBIC URLs change sometimes), see README.md for
manual download instructions.
"""

import sqlite3
import pandas as pd
import requests
import os
import sys

DB_PATH = "gst_data.db"

# Official CBIC GST rate schedule (publicly available)
# This is the master HSN/SAC + GST rates list
# Backup: download manually from https://cbic-gst.gov.in/gst-goods-services-rates.html
CBIC_HSN_URL = "https://cbic-gst.gov.in/pdf/HSN-Master-goods-rates.xlsx"

# Fallback: We also embed a minimal seed dataset so the prototype works
# even if the download fails. Real data has 5000+ entries.
SEED_DATA = [
    # (hsn_code, description, gst_rate, cess, category)
    ("0101", "Live horses, asses, mules and hinnies", 0.0, 0.0, "Goods"),
    ("0201", "Meat of bovine animals, fresh or chilled", 0.0, 0.0, "Goods"),
    ("0401", "Milk and cream, not concentrated", 0.0, 0.0, "Goods"),
    ("0402", "Milk and cream, concentrated", 5.0, 0.0, "Goods"),
    ("0801", "Coconuts, Brazil nuts, cashew nuts, fresh", 0.0, 0.0, "Goods"),
    ("0901", "Coffee, roasted", 5.0, 0.0, "Goods"),
    ("0902", "Tea, whether or not flavoured", 5.0, 0.0, "Goods"),
    ("1001", "Wheat and meslin", 0.0, 0.0, "Goods"),
    ("1006", "Rice", 5.0, 0.0, "Goods"),
    ("1101", "Wheat or meslin flour", 0.0, 0.0, "Goods"),
    ("1701", "Cane or beet sugar", 5.0, 0.0, "Goods"),
    ("2009", "Fruit juices, unfermented, packaged", 12.0, 0.0, "Goods"),
    ("2201", "Waters, natural or artificial mineral waters", 0.0, 0.0, "Goods"),
    ("2202", "Waters with added sugar - packaged drinking water > 20L", 12.0, 0.0, "Goods"),
    ("2202", "Packaged drinking water <= 20 litres", 18.0, 0.0, "Goods"),
    ("2203", "Beer made from malt", 28.0, 0.0, "Goods"),
    ("2402", "Cigars, cheroots, cigarettes", 28.0, 0.0, "Goods"),
    ("2710", "Petroleum oils", 0.0, 0.0, "Goods"),  # outside GST
    ("3004", "Medicaments for retail sale", 12.0, 0.0, "Goods"),
    ("3005", "Wadding, gauze, bandages - pharmaceutical", 12.0, 0.0, "Goods"),
    ("3401", "Soap, washing preparations", 18.0, 0.0, "Goods"),
    ("3808", "Insecticides, rodenticides, fungicides", 18.0, 0.0, "Goods"),
    ("4901", "Printed books", 0.0, 0.0, "Goods"),
    ("4902", "Newspapers, journals", 0.0, 0.0, "Goods"),
    ("4911", "Printed matter - calendars, pictures", 12.0, 0.0, "Goods"),
    ("5201", "Cotton, not carded or combed", 0.0, 0.0, "Goods"),
    ("6101", "Men's overcoats, jackets - knitted", 5.0, 0.0, "Goods"),
    ("6109", "T-shirts, singlets - knitted", 5.0, 0.0, "Goods"),
    ("6203", "Men's suits, jackets, trousers", 5.0, 0.0, "Goods"),
    ("6402", "Footwear with outer soles of rubber", 18.0, 0.0, "Goods"),
    ("7108", "Gold, unwrought or semi-manufactured", 3.0, 0.0, "Goods"),
    ("7113", "Jewellery of precious metal", 3.0, 0.0, "Goods"),
    ("8414", "Air pumps, compressors, fans", 18.0, 0.0, "Goods"),
    ("8415", "Air conditioning machines", 28.0, 0.0, "Goods"),
    ("8450", "Washing machines", 28.0, 0.0, "Goods"),
    ("8471", "Automatic data processing machines (computers)", 18.0, 0.0, "Goods"),
    ("8517", "Telephone sets including smartphones", 18.0, 0.0, "Goods"),
    ("8703", "Motor cars and other motor vehicles", 28.0, 0.0, "Goods"),
    ("8711", "Motorcycles and mopeds", 28.0, 0.0, "Goods"),
    ("9403", "Furniture - wooden", 18.0, 0.0, "Goods"),
    ("9503", "Tricycles, scooters, toy cars, puzzles", 12.0, 0.0, "Goods"),
    ("9619", "Sanitary towels, tampons, nappies", 12.0, 0.0, "Goods"),
    # SAC Codes (Services)
    ("9954", "Construction services of buildings", 18.0, 0.0, "Services"),
    ("9961", "Services in wholesale trade", 18.0, 0.0, "Services"),
    ("9962", "Services in retail trade", 18.0, 0.0, "Services"),
    ("9971", "Financial and related services", 18.0, 0.0, "Services"),
    ("9972", "Real estate services", 18.0, 0.0, "Services"),
    ("9973", "Leasing or rental services", 18.0, 0.0, "Services"),
    ("9981", "Research and development services", 18.0, 0.0, "Services"),
    ("9982", "Legal and accounting services", 18.0, 0.0, "Services"),
    ("9983", "Other professional, technical services", 18.0, 0.0, "Services"),
    ("9984", "Telecommunications services", 18.0, 0.0, "Services"),
    ("9985", "Support services - cleaning, packaging", 18.0, 0.0, "Services"),
    ("9986", "Agriculture, forestry, fishing support", 0.0, 0.0, "Services"),
    ("9987", "Maintenance, repair, installation services", 18.0, 0.0, "Services"),
    ("9988", "Manufacturing services on physical inputs", 18.0, 0.0, "Services"),
    ("9989", "Other manufacturing services", 18.0, 0.0, "Services"),
    ("9991", "Public administration, defence", 0.0, 0.0, "Services"),
    ("9992", "Education services", 0.0, 0.0, "Services"),
    ("9993", "Human health and social care services", 0.0, 0.0, "Services"),
    ("9994", "Sewage and waste collection services", 0.0, 0.0, "Services"),
    ("9995", "Arts, entertainment and recreation", 18.0, 0.0, "Services"),
    ("9996", "Sporting services, amusement parks", 18.0, 0.0, "Services"),
    ("9997", "Other services", 18.0, 0.0, "Services"),
    ("9998", "Domestic services", 0.0, 0.0, "Services"),
    ("9999", "Services by extraterritorial organisations", 0.0, 0.0, "Services"),
    # IT and Software Services
    ("998311", "Management consulting services", 18.0, 0.0, "Services"),
    ("998312", "Business consulting services", 18.0, 0.0, "Services"),
    ("998313", "IT consulting and support services", 18.0, 0.0, "Services"),
    ("998314", "Information technology design services", 18.0, 0.0, "Services"),
    ("998315", "IT infrastructure provisioning services", 18.0, 0.0, "Services"),
    ("998316", "IT technical support services", 18.0, 0.0, "Services"),
    ("998431", "Cloud computing services (SaaS)", 18.0, 0.0, "Services"),
    ("998432", "Cloud computing services (PaaS)", 18.0, 0.0, "Services"),
    ("998433", "Cloud computing services (IaaS)", 18.0, 0.0, "Services"),
]


def download_cbic_data():
    """Try to download official CBIC HSN master Excel."""
    print("Attempting to download CBIC HSN master data...")
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(CBIC_HSN_URL, headers=headers, timeout=30)
        if response.status_code == 200:
            with open("hsn_master.xlsx", "wb") as f:
                f.write(response.content)
            print("✓ Downloaded CBIC HSN master successfully")
            return True
    except Exception as e:
        print(f"✗ Download failed: {e}")
    return False


def load_from_excel(db_path):
    """Parse CBIC Excel and load into SQLite."""
    print("Loading from downloaded Excel...")
    try:
        df = pd.read_excel("hsn_master.xlsx")
        print(f"  Columns found: {list(df.columns)}")

        # CBIC Excel column names vary — normalize them
        col_map = {}
        for col in df.columns:
            c = col.lower().strip()
            if "hsn" in c or "code" in c:
                col_map["hsn_code"] = col
            elif "description" in c or "goods" in c or "service" in c:
                col_map["description"] = col
            elif "rate" in c or "gst" in c or "igst" in c:
                col_map["gst_rate"] = col
            elif "cess" in c:
                col_map["cess"] = col

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        _create_tables(cursor)

        count = 0
        for _, row in df.iterrows():
            try:
                hsn = str(row.get(col_map.get("hsn_code", ""), "")).strip()
                desc = str(row.get(col_map.get("description", ""), "")).strip()
                rate = float(row.get(col_map.get("gst_rate", ""), 0) or 0)
                cess = float(row.get(col_map.get("cess", ""), 0) or 0)
                category = "Services" if hsn.startswith("99") else "Goods"

                if hsn and desc and len(hsn) >= 4:
                    cursor.execute(
                        "INSERT OR REPLACE INTO hsn_data VALUES (?,?,?,?,?)",
                        (hsn, desc, rate, cess, category),
                    )
                    count += 1
            except Exception:
                continue

        conn.commit()
        conn.close()
        print(f"✓ Loaded {count} HSN/SAC entries from CBIC Excel")
        return True
    except Exception as e:
        print(f"✗ Excel parsing failed: {e}")
        return False


def load_seed_data(db_path):
    """Load the built-in seed dataset as fallback."""
    print("Loading seed dataset (prototype mode)...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    _create_tables(cursor)

    for row in SEED_DATA:
        cursor.execute(
            "INSERT OR REPLACE INTO hsn_data VALUES (?,?,?,?,?)", row
        )

    conn.commit()
    conn.close()
    print(f"✓ Loaded {len(SEED_DATA)} entries from seed data")
    print()
    print("NOTE: Seed data covers common goods/services for prototyping.")
    print("For production, download the full CBIC HSN master from:")
    print("https://cbic-gst.gov.in/gst-goods-services-rates.html")


def _create_tables(cursor):
    """Create the HSN data table."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hsn_data (
            hsn_code    TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            gst_rate    REAL DEFAULT 0,
            cess        REAL DEFAULT 0,
            category    TEXT DEFAULT 'Goods'
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_description 
        ON hsn_data(description)
    """)


def main():
    if os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} already exists.")
        ans = input("Rebuild from scratch? (y/n): ").strip().lower()
        if ans != "y":
            print("Keeping existing database.")
            return
        os.remove(DB_PATH)

    # Use already-downloaded file if it exists, otherwise try to download
    if os.path.exists("hsn_master.xlsx"):
        print("Found existing hsn_master.xlsx, using it...")
        success = load_from_excel(DB_PATH)
        if not success:
            print("Excel parsing failed, falling back to seed data...")
            load_seed_data(DB_PATH)
    else:
        downloaded = download_cbic_data()
        if downloaded:
            success = load_from_excel(DB_PATH)
            if not success:
                load_seed_data(DB_PATH)
        else:
            load_seed_data(DB_PATH)

    # Verify
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM hsn_data").fetchone()[0]
    conn.close()
    print(f"\n✓ Database ready: {count} HSN/SAC entries in {DB_PATH}")
    print("✓ You can now run: python server.py")


if __name__ == "__main__":
    main()

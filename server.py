"""
server.py
---------
GST Rate Lookup MCP Server

Exposes 3 tools to Claude (or any MCP client):
  1. search_hsn        - Find HSN/SAC codes by keyword
  2. get_rate_by_hsn   - Get GST rate(s) for a known HSN/SAC code
  3. compare_products  - Compare GST rates across multiple products

DB schema (built by load_from_excel.py):
  hsn_data(line_id PK, hsn_code, description, gst_rate, cess, category, schedule)
  Note: multiple rows per hsn_code are intentional — same HSN can have
  different rates for different product states (e.g. fresh vs packaged,
  <350cc vs >350cc motorcycles).

Run locally:
    python server.py

Claude Desktop config (claude_desktop_config.json):
    {
      "mcpServers": {
        "gst-lookup": {
          "command": "python",
          "args": ["\\server.py"]
        }
      }
    }
"""

import sqlite3
import json
from typing import Optional
from fastmcp import FastMCP

import os as _os
DB_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "gst_data.db")

mcp = FastMCP(
    name="GST Rate Lookup India",
    instructions="""
    You are a GST (Goods and Services Tax) lookup assistant for India.
    You have access to official CBIC data via tools — always use these tools
    to answer GST questions. NEVER use your own training knowledge for GST
    rates as it may be outdated.

    CRITICAL RULES:
    - ALWAYS call a tool first before stating any GST rate
    - Report EXACTLY the rates returned by the tool — do not adjust, override,
      or supplement with rates from your own knowledge
    - Do NOT add cess figures unless the tool explicitly returns a non-zero cess value
    - When the tool returns multiple rates for the same HSN, show ALL of them
      with their descriptions (e.g. fresh vs packaged, engine size variants)
    - Always mention the HSN code alongside the rate
    - Advise users to verify with a CA for statutory compliance

    Data source: Notification 09/2025-CT(Rate), effective 22 September 2025.

    Invoice HSN digit requirements by annual turnover:
        Up to ₹5 crore   → 4-digit HSN
        ₹5–20 crore      → 6-digit HSN
        Above ₹20 crore  → 8-digit HSN
    """,
)


# ── DB helper ─────────────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        raise RuntimeError(
            f"Database not found. Run 'python load_from_excel.py' first. ({e})"
        )


def row_to_dict(row: sqlite3.Row) -> dict:
    rate     = row["gst_rate"]
    cess     = row["cess"]
    has_cess = bool(row["has_cess"]) if "has_cess" in row.keys() else False
    hsn_lvl  = row["hsn_level"]     if "hsn_level" in row.keys() else None
    return {
        "hsn_code":        row["hsn_code"],
        "description":     row["description"],
        "schedule":        row["schedule"],
        "category":        row["category"],
        "hsn_level":       hsn_lvl,
        "igst_percent":    rate,
        "cgst_percent":    rate / 2,
        "sgst_percent":    rate / 2,
        "cess_percent":    cess,
        "cess_applicable": has_cess,
        "total_percent":   rate + cess,
        "is_exempt":       rate == 0,
    }


# ── Tool 1: search_hsn ────────────────────────────────────────────────────────

@mcp.tool()
def search_hsn(
    query: str,
    category: Optional[str] = None,
    limit: int = 10,
) -> str:
    """
    Search for HSN (goods) or SAC (services) codes by product/service name.

    Use when the user describes a product in plain English and wants the
    GST rate. Returns all matching entries — including cases where the same
    HSN code has different rates for different product variants.

    Args:
        query:    Product description e.g. "coconut oil", "motorcycle", "packaged water"
        category: Optional "Goods" or "Services" filter
        limit:    Max results (default 10)
    """
    if not query or len(query.strip()) < 2:
        return json.dumps({"error": "Query too short."})

    words  = query.strip().lower().split()
    conn   = get_db()

    try:
        # AND search first (all words must appear)
        conditions = ["LOWER(description) LIKE ?" for _ in words]
        params     = [f"%{w}%" for w in words]
        sql = (
            f"SELECT * FROM hsn_data "
            f"WHERE {' AND '.join(conditions)}"
        )
        if category in ("Goods", "Services"):
            sql   += " AND category = ?"
            params.append(category)
        sql += f" ORDER BY length(hsn_code) ASC, gst_rate DESC LIMIT {int(limit)}"

        rows = conn.execute(sql, params).fetchall()

        # Fallback: OR search if nothing found
        if not rows and len(words) > 1:
            conditions = ["LOWER(description) LIKE ?" for _ in words]
            params     = [f"%{w}%" for w in words]
            sql = (
                f"SELECT * FROM hsn_data "
                f"WHERE {' OR '.join(conditions)}"
            )
            if category in ("Goods", "Services"):
                sql   += " AND category = ?"
                params.append(category)
            sql += f" ORDER BY length(hsn_code) ASC, gst_rate DESC LIMIT {int(limit)}"
            rows = conn.execute(sql, params).fetchall()

        if not rows:
            return json.dumps({
                "found":   0,
                "query":   query,
                "message": f"No entries found for '{query}'. Try broader terms.",
                "results": [],
            })

        return json.dumps({
            "found":   len(rows),
            "query":   query,
            "results": [row_to_dict(r) for r in rows],
        }, indent=2)

    finally:
        conn.close()


# ── Tool 2: get_rate_by_hsn ───────────────────────────────────────────────────

@mcp.tool()
def get_rate_by_hsn(hsn_code: str) -> str:
    """
    Get GST rate(s) for a known HSN or SAC code.

    Returns ALL rate entries for the code — important because some HSN codes
    legitimately have multiple rates (e.g. HSN 8711 motorcycles: 18% for
    engine ≤350cc, 40% for >350cc).

    Args:
        hsn_code: HSN code (4-8 digits) or SAC code (6 digits)
                  e.g. "8517", "870321", "2202"
    """
    if not hsn_code:
        return json.dumps({"error": "Please provide an HSN or SAC code."})

    code = hsn_code.strip().replace(" ", "").replace(".", "")
    conn = get_db()

    try:
        # Build list of codes to try: original + leading-zero-stripped variant
        # The Excel dataset stores some codes without leading zeros (901 vs 0901)
        candidates = [code]
        stripped   = code.lstrip("0")
        if stripped and stripped != code:
            candidates.append(stripped)

        rows = []
        for candidate in candidates:
            rows = conn.execute(
                "SELECT * FROM hsn_data WHERE hsn_code = ? ORDER BY gst_rate",
                (candidate,),
            ).fetchall()
            if rows:
                break

        # Prefix fallback — try progressively shorter prefixes
        if not rows:
            for length in [len(code) - 2, 6, 4, 2]:
                if length >= 2 and length < len(code):
                    for candidate in candidates:
                        prefix = candidate[:length]
                        rows   = conn.execute(
                            "SELECT * FROM hsn_data WHERE hsn_code = ? ORDER BY gst_rate",
                            (prefix,),
                        ).fetchall()
                        if rows:
                            break
                if rows:
                    break

        if not rows:
            return json.dumps({
                "found":    False,
                "hsn_code": code,
                "message":  (
                    f"HSN '{code}' not found. It may be covered by a broader "
                    "chapter heading — try search_hsn with the product name."
                ),
            })

        entries = [row_to_dict(r) for r in rows]

        # If multiple rates exist, flag it prominently
        rates = list({e["igst_percent"] for e in entries})
        multi = len(rates) > 1

        return json.dumps({
            "found":          True,
            "hsn_code":       code,
            "multiple_rates": multi,
            "note": (
                f"This HSN has {len(rates)} different rates depending on "
                "the specific product variant — see entries below."
                if multi else
                "Verify exact classification with a CA before filing."
            ),
            "entries": entries,
        }, indent=2)

    finally:
        conn.close()


# ── Tool 3: compare_products ──────────────────────────────────────────────────

@mcp.tool()
def compare_products(products: list[str]) -> str:
    """
    Compare GST rates across multiple products side by side.

    Args:
        products: List of 2-10 product names
                  e.g. ["fresh milk", "packaged milk", "cheese", "paneer"]
    """
    if not products or len(products) < 2:
        return json.dumps({"error": "Provide at least 2 products."})
    if len(products) > 10:
        return json.dumps({"error": "Maximum 10 products per comparison."})

    conn       = get_db()
    comparison = []

    try:
        for product in products:
            product = product.strip()
            if not product:
                continue

            words      = product.lower().split()
            conditions = ["LOWER(description) LIKE ?" for _ in words]
            params     = [f"%{w}%" for w in words]

            rows = conn.execute(
                f"SELECT * FROM hsn_data "
                f"WHERE {' AND '.join(conditions)} "
                f"ORDER BY length(hsn_code) ASC, gst_rate DESC "
                f"LIMIT 3",   # top 3 matches to catch multi-rate HSNs
                params,
            ).fetchall()

            if rows:
                best = rows[0]
                entry = {
                    "searched_for":  product,
                    "found":         True,
                    "best_match":    best["description"],
                    "hsn_code":      best["hsn_code"],
                    "igst_percent":  best["gst_rate"],
                    "total_percent": best["gst_rate"] + best["cess"],
                    "is_exempt":     best["gst_rate"] == 0,
                }
                # Note if multiple rates exist for this HSN
                all_rates = list({r["gst_rate"] for r in rows})
                if len(all_rates) > 1:
                    entry["rate_variants"] = sorted(all_rates)
                    entry["note"] = "Multiple rates exist — check get_rate_by_hsn for details"
                comparison.append(entry)
            else:
                comparison.append({
                    "searched_for": product,
                    "found":        False,
                    "message":      "Not found — try different keywords",
                })

        found = [x for x in comparison if x.get("found")]
        found.sort(key=lambda x: x.get("total_percent", 0))
        not_found = [x for x in comparison if not x.get("found")]

        rates   = [x["igst_percent"] for x in found]
        summary = {}
        if rates:
            summary = {
                "lowest_rate":      min(rates),
                "highest_rate":     max(rates),
                "products_found":   len(found),
                "exempt_products":  sum(1 for r in rates if r == 0),
            }

        return json.dumps({
            "comparison": found + not_found,
            "summary":    summary,
        }, indent=2)

    finally:
        conn.close()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os, sys
    if not os.path.exists(DB_PATH):
        print(f"ERROR: '{DB_PATH}' not found.", file=sys.stderr)
        print("Run first:  python load_from_excel.py", file=sys.stderr)
        exit(1)
    print(f"GST MCP Server starting, DB: {DB_PATH}", file=sys.stderr)
    mcp.run()
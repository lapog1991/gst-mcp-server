# 🇮🇳 GST Rate Lookup — MCP Server

An MCP (Model Context Protocol) server that lets Claude answer GST-related
questions using official CBIC HSN/SAC master data. Built for India.

> **Disclaimer:** Data is sourced from publicly available CBIC notifications.
> Always verify with official GST sources or a CA for statutory compliance.

---

## What it does

Adds 3 tools to Claude:

| Tool | What it answers |
|---|---|
| `search_hsn` | "What is the GST rate on packaged tender coconut water?" |
| `get_rate_by_hsn` | "Give me the full breakdown for HSN 8517" |
| `compare_products` | "Compare GST rates for gold, diamonds, and silver jewellery" |

**Example conversations:**

> *"I sell handmade cotton kurtas. What HSN code applies and what's the GST rate?"*

> *"What's the difference in GST between packaged and fresh coconut water?"*

> *"I'm a freelance software developer. What SAC code do I use and what GST do I charge?"*

> *"Compare GST rates for: smartphones, laptops, LED TVs, and air conditioners"*

---

## Setup (5 minutes)

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Build the database

```bash
python load_from_excel.py
```

This will:
- Parse `GST_dataset_for_MCP.xlsx` (Notification 09/2025-CT(Rate), 22 Sept 2025)
- Merge HSN levels from `GST_CGST_Rates_Clean.xlsx`
- Load 1500 rows with 1194 unique HSN codes into `gst_data.db`
- Run 24 spot checks automatically to verify data integrity

You should see at the end:
```
✅  All spot checks passed — database is ready!
    Next step:  python server.py
```

### 3. Run the server

```bash
python server.py
```

That's it! Two steps and you're live.

---

## Add to Claude Desktop

Edit your Claude Desktop config file:

**Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "gst-lookup": {
      "command": "python",
      "args": ["/full/path/to/server.py"]
    }
  }
}
```

Restart Claude Desktop. You'll see "gst-lookup" appear in the tools menu.

---

## Making it public (remote MCP server)

### Update server.py for remote hosting

Change the last line in `server.py` from:
```python
mcp.run()
```
To:
```python
mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

### Deploy to Render (free)

1. Push this repo to GitHub
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Set:
   - **Build command:** `pip install -r requirements.txt && python load_from_excel.py`
   - **Start command:** `python server.py`
5. Deploy → get your public URL e.g. `https://gst-mcp.onrender.com`

### Connect via Claude.ai

Go to **Claude.ai → Settings → Integrations → Add MCP Server** and paste your URL.

### Claude Desktop config for remote server

```json
{
  "mcpServers": {
    "gst-lookup": {
      "url": "https://gst-mcp.onrender.com"
    }
  }
}
```

---

## Submit to MCP directories

Once deployed, submit your server to:

- **Glama.ai** → https://glama.ai/mcp/submit
- **mcp.so** → https://mcp.so/submit
- **Smithery.ai** → https://smithery.ai

---

## Keeping data updated

GST rates change when the GST Council meets (roughly every 3-6 months).

To update:
1. Download the latest notification Excel from the CBIC website
2. Replace `GST_dataset_for_MCP.xlsx` in this folder
3. Run `python load_from_excel.py` → choose `y` to rebuild
4. Redeploy

---

## Data source

Built from **Notification 09/2025-CT(Rate), dated 22 September 2025** — the most recent GST rate revision.

- 1500 rows loaded
- 1194 unique HSN codes
- 24 spot checks passing including edge cases (OR-conditions, cess items, NIL entries)

---

## Project structure

```
gst-mcp-server/
├── server.py                    # MCP server — 3 tools
├── load_from_excel.py           # Database builder from Excel data
├── gst_data.db                  # SQLite database (generated)
├── GST_dataset_for_MCP.xlsx     # Source data (Notification 09/2025)
├── requirements.txt             # Python dependencies
└── README.md                    # This file
```

---

## Tech stack

- **FastMCP** — Python MCP server framework
- **SQLite** — local database, zero config
- **pandas** — Excel parsing
- **Data source** — CBIC (Central Board of Indirect Taxes and Customs)

---

## License

MIT — free to use, modify, and publish.

---

*Built for India 🇮🇳 — solving real GST classification problems with open government data.*
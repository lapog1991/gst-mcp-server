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
cd gst-mcp
pip install -r requirements.txt
```

### 2. Build the database

```bash
python setup_db.py
```

This will:
- Try to download the official CBIC HSN master Excel
- If download fails, load the built-in seed dataset (good for prototyping)

**For production — manual data download (recommended):**
1. Go to https://cbic-gst.gov.in/gst-goods-services-rates.html
2. Download the HSN/SAC master Excel
3. Place it in this folder as `hsn_master.xlsx`
4. Run `python setup_db.py` — it will parse it automatically

### 3. Test the server

```bash
python server.py
```

You should see:
```
Starting GST Rate Lookup MCP Server...
Database: gst_data.db
Ready for connections.
```

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
      "args": ["/full/path/to/gst-mcp/server.py"]
    }
  }
}
```

Restart Claude Desktop. You'll see "gst-lookup" appear in the tools menu.

---

## Making it public (remote MCP server)

### Deploy to Render (free)

1. Push this repo to GitHub
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Set:
   - **Build command:** `pip install -r requirements.txt && python setup_db.py`
   - **Start command:** `python server.py`
5. Deploy → get your URL e.g. `https://gst-mcp.onrender.com`

### Update server.py for remote hosting

Add this to `server.py` before `mcp.run()`:

```python
mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

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
1. Download latest HSN master from CBIC website
2. Place as `hsn_master.xlsx` in this folder
3. Run `python setup_db.py` → choose `y` to rebuild
4. Redeploy

---

## Project structure

```
gst-mcp/
├── server.py          # MCP server — 3 tools
├── setup_db.py        # Database builder from CBIC data
├── gst_data.db        # SQLite database (generated)
├── requirements.txt   # Python dependencies
└── README.md          # This file
```

---

## Tech stack

- **FastMCP** — Python MCP server framework
- **SQLite** — local database, zero config
- **pandas** — Excel parsing for CBIC data
- **Data source** — CBIC (Central Board of Indirect Taxes and Customs)

---

## License

MIT — free to use, modify, and publish.

---

*Built for India 🇮🇳 — solving real problems with open government data.*

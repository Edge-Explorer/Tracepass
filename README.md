# 🕷️ Tracepass — Autonomous Web Scraping & Media Extraction Framework

> An AI-powered multi-agent system for intelligent, fingerprint-free web scraping, media extraction, and deep-crawl automation — built on [Scrapling](https://github.com/D4Vinci/Scrapling).

---

## 📌 Overview

**Tracepass** is a hierarchical multi-agent framework that lets you extract *any* data from *any* website using natural language instructions. Powered by Scrapling under the hood, it bypasses bot-detection systems (including Cloudflare), leaves no fingerprints, and navigates sites autonomously to fulfill complex data requests — images, videos, audio, documents, structured data, and more.

```
"Go to xyz.com and get all audio files related to classical music"
        ↓
  [Main Agent] → [Researcher Sub-Agent] → [Code Generator] → [Executor] → 📦 Results
```

---

## 🏗️ Architecture

```
Tracepass/
├── agents/
│   ├── main_agent.py           # Orchestrator — routes tasks, manages state
│   ├── researcher_agent.py     # Sub-agent — resolves URLs, maps site structure
│   └── code_generator.py       # Generates Scrapling code dynamically per URL
├── tools/
│   ├── scraper_executor.py     # Executes generated Scrapling code safely
│   ├── html_parser.py          # Strips CSS/JS, returns clean tag tree
│   └── media_extractor.py      # Handles image / video / audio / document download
├── core/
│   ├── agent_loop.py           # Deep-crawl loop — iterates until result found
│   ├── url_resolver.py         # Validates and resolves relative → absolute URLs
│   └── state_manager.py        # Tracks crawl state, depth, and visited nodes
├── config/
│   └── settings.py             # Model, depth limits, output paths, timeouts
├── outputs/                    # Downloaded media and extracted data land here
├── tests/
│   └── ...
├── requirements.txt
└── README.md
```

---

## 🔄 How It Works

### Step 1 — User Instruction
The user provides a natural language request:
```
"Get all product images from store.example.com for the 'shoes' category"
```

### Step 2 — Researcher Sub-Agent
- Resolves the target URL (searches if needed)
- Maps the site's navigation structure
- Returns the most relevant entry-point URL to the Main Agent

### Step 3 — Main Agent: Code Generation
- Receives the URL from the Researcher
- Dynamically generates Scrapling scraper code tailored to that URL
- Passes the code to the Scraper Executor tool

### Step 4 — Scraper Executor
- Runs the generated Scrapling code in a sandboxed environment
- Returns raw HTML with CSS/JS stripped — a clean tag tree
- Passes the page content back to the Main Agent

### Step 5 — Deep-Crawl Loop
- Main Agent analyzes the tag tree to find links, `src` attributes, or paths leading to the target resource
- Generates new Scrapling code for the next-level URL
- Repeats until the desired resource (image / video / audio / data) is found and downloaded

```
[Instruction]
     ↓
[Researcher Agent] ──→ URL
     ↓
[Main Agent]
     ↓
[Code Generator] ──→ Scrapling Code
     ↓
[Executor] ──→ Raw HTML / Tag Tree
     ↓
[Main Agent analyzes] ──→ Target found? 
     │                         ↓ YES → Download & Return
     └── NO → Go deeper (repeat from Code Generator)
```

---

## ⚙️ Tech Stack

| Component | Technology |
|---|---|
| Scraping Engine | [Scrapling](https://github.com/D4Vinci/Scrapling) |
| Agent Framework | LangGraph / LangChain |
| LLM Backend | (configurable — OpenAI / Bedrock / Ollama) |
| HTML Parsing | BeautifulSoup4 + lxml |
| Media Downloading | yt-dlp (video/audio), httpx (images/files) |
| Execution Sandbox | RestrictedPython / subprocess isolation |
| State Management | LangGraph StateGraph |

---

## 🚀 Quickstart

### 1. Clone & Install

```bash
git clone https://github.com/your-org/tracepass.git
cd tracepass
pip install -r requirements.txt
playwright install   # Required by Scrapling for JS-rendered pages
```

### 2. Configure

```python
# config/settings.py
LLM_PROVIDER = "openai"  # or "bedrock", "ollama"
MODEL_NAME = "gpt-4o"
MAX_DEPTH = 5  # Max crawl depth before giving up
OUTPUT_DIR = "./outputs"
```

### 3. Run

```python
from agents.main_agent import Tracepass

agent = Tracepass()
result = agent.run("Go to unsplash.com and download 10 images of mountains")
print(result)
```

---

## 🧪 Example Requests

```python
# Download all images matching a query
agent.run("Get all images of sunsets from pexels.com")

# Download a video
agent.run("Download the intro video from apple.com/macbook-pro")

# Extract structured data
agent.run("Get all product names and prices from the electronics section of example-store.com")

# Download audio files
agent.run("Find all podcast audio files on xyz.com/podcasts")

# Deep crawl for a document
agent.run("Find and download the annual report PDF from investor.example.com")
```

---

## 🛡️ Why Scrapling?

- ✅ Zero bot fingerprints — mimics real browser behavior
- ✅ Bypasses Cloudflare and common CAPTCHA systems
- ✅ Supports both static and JS-rendered pages
- ✅ Fast — built on Playwright with stealth patches
- ✅ No browser automation overhead for simple pages

---

## 📋 Requirements

```
scrapling
langchain
langgraph
langchain-openai       # or langchain-aws for Bedrock
beautifulsoup4
lxml
httpx
yt-dlp
playwright
restrictedpython
```

---

## ⚠️ Legal & Ethical Notice

This tool is intended for **legitimate use cases only** — research, personal archiving, and data collection from sites that permit it. Always check a website's `robots.txt` and Terms of Service before scraping. The authors are not responsible for misuse of this framework.

---

## 🗺️ Roadmap

- [ ] Multi-threaded parallel crawling
- [ ] Browser session caching for faster repeat visits
- [ ] Output formats: JSON, CSV, SQLite
- [ ] REST API wrapper for remote agent calls
- [ ] Dashboard UI for crawl monitoring
- [ ] Docker deployment support

---

## 🤝 Contributing

PRs are welcome. Please open an issue first to discuss major changes.

---

## 📄 License

MIT License — see [LICENSE](./LICENSE) for details.
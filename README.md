# Tracepass

**Autonomous Web Scraping and Media Extraction Framework**

Tracepass is a hierarchical, multi-agent framework for intelligent, fingerprint-free web scraping, media extraction, and deep-crawl automation. It accepts natural language instructions and autonomously navigates websites to retrieve images, videos, audio files, documents, and structured data — without leaving browser fingerprints or triggering bot-detection systems.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Usage Examples](#usage-examples)
- [Why Scrapling](#why-scrapling)
- [CI/CD Pipeline](#cicd-pipeline)
- [Development Setup](#development-setup)
- [Requirements](#requirements)
- [Roadmap](#roadmap)
- [Legal and Ethical Notice](#legal-and-ethical-notice)
- [Contributing](#contributing)
- [License](#license)

---

## Overview

Tracepass abstracts the complexity of web scraping into a single natural language interface. You describe what you want, and the agent pipeline resolves the URL, generates scraper code tailored to the target page, executes it, parses the result, and drills deeper until the target resource is found and downloaded.

It is designed for:

- Researchers and data engineers who need repeatable, large-scale media collection workflows.
- Developers building data pipelines that consume content from the open web.
- Teams that require an autonomous scraping layer plugged into a larger LLM-based system.

**Example invocation:**

```
"Go to xyz.com and get all audio files related to classical music"

[Main Agent] -> [Researcher Sub-Agent] -> [Code Generator] -> [Executor] -> Results
```

---

## Architecture

```
Tracepass/
├── agents/
│   ├── main_agent.py           # Orchestrator: routes tasks, manages crawl state
│   ├── researcher_agent.py     # Sub-agent: resolves URLs, maps site structure
│   └── code_generator.py       # Generates Scrapling scraper code dynamically per URL
├── tools/
│   ├── scraper_executor.py     # Executes generated Scrapling code in a sandboxed environment
│   ├── html_parser.py          # Strips CSS and JS, returns a clean semantic tag tree
│   └── media_extractor.py      # Handles downloading of images, video, audio, and documents
├── core/
│   ├── agent_loop.py           # Deep-crawl loop: iterates across pages until target is found
│   ├── url_resolver.py         # Validates and resolves relative URLs to absolute form
│   └── state_manager.py        # Tracks crawl state, visited nodes, and recursion depth
├── config/
│   └── settings.py             # LLM provider, depth limits, output paths, and timeouts
├── outputs/                    # Downloaded media and extracted data are written here
├── tests/
│   └── ...
├── .github/
│   ├── workflows/
│   │   ├── ci.yml              # Ruff lint, format checks, and pytest
│   │   └── gemini-pr-summary.yml  # Automated PR review via Gemini 2.5 Flash
│   └── scripts/
│       └── gemini_pr_summary.py   # Gemini PR summary generation script
├── pyproject.toml
└── README.md
```

---

## How It Works

### Step 1 — Natural Language Instruction

The user provides a plain-English request describing the target website and desired content:

```
"Get all product images from store.example.com for the shoes category"
```

### Step 2 — Researcher Sub-Agent

The Researcher Sub-Agent is invoked first. It:

- Resolves the target URL, running a web search if the user provides a partial or ambiguous reference.
- Crawls the site's top-level navigation to map its structural entry points.
- Returns the most relevant starting URL to the Main Agent.

### Step 3 — Code Generation

The Main Agent receives the resolved URL and passes it to the Code Generator, which:

- Inspects the URL structure and any available metadata.
- Produces a Scrapling scraper script tailored to the specific page layout and content type.
- Delivers the generated script to the Scraper Executor tool.

### Step 4 — Scraper Executor

The Scraper Executor:

- Runs the generated Scrapling code inside a sandboxed environment.
- Returns raw HTML with all CSS and JavaScript stripped, yielding a clean semantic tag tree.
- Passes the processed content back to the Main Agent for analysis.

### Step 5 — Deep-Crawl Loop

The Main Agent analyzes the tag tree for links, `src` attributes, and URL patterns that lead to the target resource. If the resource is not present on the current page, it:

- Generates a new scraper for the next-level URL.
- Re-executes the pipeline.
- Repeats this loop until the desired resource is located, then downloads and returns it.

```
[Instruction]
     |
[Researcher Agent] --> URL
     |
[Main Agent]
     |
[Code Generator] --> Scrapling Code
     |
[Executor] --> Raw HTML / Tag Tree
     |
[Main Agent analyzes] --> Target found?
     |                         |
     |                    YES  --> Download and Return
     |
    NO --> Go deeper (repeat from Code Generator)
```

---

## Tech Stack

| Component           | Technology                                          |
| :------------------ | :-------------------------------------------------- |
| Scraping Engine     | [Scrapling](https://github.com/D4Vinci/Scrapling)  |
| Agent Framework     | LangGraph / LangChain                               |
| LLM Backend         | Configurable: OpenAI, Google Gemini, Bedrock, Ollama |
| HTML Parsing        | BeautifulSoup4 + lxml                               |
| Media Downloading   | yt-dlp (video and audio), httpx (images and files) |
| Execution Sandbox   | RestrictedPython / subprocess isolation             |
| State Management    | LangGraph StateGraph                                |
| Package Management  | [uv](https://github.com/astral-sh/uv)              |
| Linting/Formatting  | [Ruff](https://github.com/astral-sh/ruff)          |
| Testing             | pytest                                              |
| Automated PR Review | Gemini 2.5 Flash + CodeRabbit                       |

---

## Quickstart

### Prerequisites

- Python 3.12 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or pip
- An API key for your chosen LLM provider (OpenAI, Gemini, etc.)

### 1. Clone the Repository

```bash
git clone https://github.com/Edge-Explorer/Tracepass.git
cd Tracepass
```

### 2. Install Dependencies

Using `uv` (recommended):

```bash
uv sync
```

Or using pip:

```bash
pip install -e .
playwright install   # Required by Scrapling for JavaScript-rendered pages
```

### 3. Set Up Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your API credentials:

```env
GEMINI_API_KEY=your_gemini_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
LLM_PROVIDER=gemini
MODEL_NAME=gemini-2.5-flash
MAX_DEPTH=5
OUTPUT_DIR=./outputs
```

### 4. Run

```python
from agents.main_agent import Tracepass

agent = Tracepass()
result = agent.run("Go to unsplash.com and download 10 images of mountains")
print(result)
```

---

## Configuration

All runtime parameters are managed through `config/settings.py` or via environment variables defined in `.env`.

| Parameter      | Default            | Description                                         |
| :------------- | :----------------- | :-------------------------------------------------- |
| `LLM_PROVIDER` | `gemini`           | LLM backend to use: `gemini`, `openai`, `ollama`    |
| `MODEL_NAME`   | `gemini-2.5-flash` | Model identifier for the chosen provider            |
| `MAX_DEPTH`    | `5`                | Maximum crawl recursion depth before aborting       |
| `OUTPUT_DIR`   | `./outputs`        | Directory where downloaded media and data are saved |
| `LOG_LEVEL`    | `INFO`             | Logging verbosity: `DEBUG`, `INFO`, `WARNING`       |

---

## Usage Examples

```python
# Download images matching a query
agent.run("Get all images of sunsets from pexels.com")

# Download a video from a specific page
agent.run("Download the intro video from apple.com/macbook-pro")

# Extract structured tabular data
agent.run("Get all product names and prices from the electronics section of example-store.com")

# Collect audio files from a podcast directory
agent.run("Find all podcast audio files on xyz.com/podcasts")

# Locate and download a PDF document via deep crawl
agent.run("Find and download the annual report PDF from investor.example.com")
```

---

## Why Scrapling

Tracepass is built on [Scrapling](https://github.com/D4Vinci/Scrapling) because it provides a scraping foundation that is production-ready for adversarial environments:

- **Zero browser fingerprints.** Scrapling mimics legitimate browser behavior at the TLS and HTTP/2 header level, making requests indistinguishable from real users.
- **Cloudflare and CAPTCHA bypass.** Through Camoufox and stealth-patched Playwright, Scrapling successfully handles bot-detection layers that block conventional scrapers.
- **Static and dynamic page support.** Scrapling selects the appropriate fetcher automatically — a lightweight HTTP client for static pages and a full browser engine for JavaScript-rendered content — minimizing overhead.
- **High-speed execution.** Playwright with stealth patches provides a fast and reliable execution environment for complex, JS-heavy websites.

---

## CI/CD Pipeline

Tracepass uses a fully automated CI/CD pipeline enforced on every pull request to `main`.

### Automated Checks (GitHub Actions)

Every pull request triggers two mandatory workflow jobs defined in `.github/workflows/ci.yml`:

- **Lint and Format** — runs `ruff check .` and `ruff format --check .` to enforce code style and catch common errors.
- **Tests** — installs all development dependencies via `uv sync --extra dev` and runs the full test suite with `pytest`.

Both checks must pass before a pull request is eligible for merging.

### Automated Pull Request Review

Every pull request automatically receives a structured code review comment generated by **Gemini 2.5 Flash**, delivered by the workflow in `.github/workflows/gemini-pr-summary.yml`. The review covers:

- **Executive Summary** — plain-English overview of the changes.
- **Motivation and Root Cause Analysis** — why the change was needed.
- **Step-by-Step Technical Solution** — precise breakdown of the implementation.
- **File-by-File Breakdown** — a detailed table documenting every changed file, the action taken, and the specific logic or configuration introduced.
- **Architecture, Reliability, and Security Considerations** — analysis of design quality and potential risks.
- **Risk Assessment** — overall risk rating with a list of edge cases to verify.
- **Reviewer Checklist** — actionable verification steps for the code reviewer.

In addition, **CodeRabbit** is configured via `.coderabbit.yaml` to provide automated inline code review comments directly on the diff.

### Branch Protection

The `main` branch is protected by the following ruleset:

- Direct pushes to `main` are blocked for all collaborators, including repository owners.
- All changes must be submitted as pull requests.
- At least one approving review from a collaborator with write access is required before merging.
- The `Lint and Format` and `Tests` status checks must pass before merging is permitted.
- Force pushes and branch deletion are blocked.
- Stale approvals are dismissed when new commits are pushed to an open pull request.

---

## Development Setup

Install the development dependencies:

```bash
uv sync --extra dev
```

Run the linter:

```bash
uvx ruff check .
```

Run the formatter:

```bash
uvx ruff format .
```

Run the test suite:

```bash
uv run pytest -v
```

---

## Requirements

Core dependencies are declared in `pyproject.toml`. Key packages include:

```
scrapling[all,fetchers]>=0.4.15
langchain
langgraph
langchain-openai
beautifulsoup4
lxml
httpx
yt-dlp
playwright
restrictedpython
```

Development dependencies:

```
pytest>=8.0.0
ruff>=0.9.0
```

---

## Roadmap

- [ ] Multi-threaded parallel crawling across multiple URLs simultaneously
- [ ] Browser session caching for faster repeat visits to the same domain
- [ ] Structured output formats: JSON, CSV, and SQLite export
- [ ] REST API wrapper for remote agent invocation
- [ ] Dashboard UI for real-time crawl monitoring and history
- [ ] Docker deployment support with pre-configured Playwright environment

---

## Legal and Ethical Notice

Tracepass is intended for legitimate use cases only, including academic research, personal data archiving, and data collection from websites that explicitly permit it. Before using this tool against any website, you must review its `robots.txt` file and Terms of Service. The authors and contributors assume no responsibility for any misuse of this framework. Scraping websites in violation of their terms of service or applicable law is solely the responsibility of the operator.

---

## Contributing

Contributions are welcome. Please open an issue first to discuss the scope and design of any significant changes. All pull requests must pass the CI checks and receive at least one approving review before they are eligible for merging.

See the [CI/CD Pipeline](#cicd-pipeline) section for details on the automated review and quality gate processes applied to every contribution.

---

## License

MIT License. See [LICENSE](./LICENSE) for the full text.
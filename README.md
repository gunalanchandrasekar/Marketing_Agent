# Marketing_Agent

AI-assisted tender and opportunity discovery — Phase 1: public web search, crawling and document collection.

## Requirements
- Python 3.11+
- Network access to public search providers and websites
- Optional: a functioning SearXNG service with JSON responses enabled

## Windows setup (PowerShell)
```powershell
git clone https://github.com/gunalanchandrasekar/Marketing_Agent.git
cd Marketing_Agent
git checkout Dev_Guna
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

## Run
```powershell
python scraper.py --topic "DigiLocker" --max-pages 20 --max-documents 5
```
By default searches use the `ddgs` library. For a locally hosted SearXNG with JSON enabled:
```powershell
python scraper.py --topic "DigiLocker" --searxng http://localhost:8081
```
SearXNG instances may block `format=json` or return HTTP 403. Test first:
```powershell
curl.exe "http://localhost:8081/search?q=DigiLocker&format=json"
```
If JSON is unavailable, omit the `--searxng` argument and use DDGS. Search providers can rate-limit or reject requests. Failures are recorded under `errors` rather than silently swallowed.

## Outputs
- `data/results.json`: queries, candidate counts, fetched page text, linked documents, failure details
- `data/documents/`: downloaded PDF/DOC/DOCX files named by SHA-256

## Tests
```powershell
pytest -q
```

## Present scope and limitations
- This is a **discovery foundation**, not a tender deadline extraction or AI analysis engine.
- Search queries cover government procurement and public community discussions.
- It follows direct public search hits; it does not currently deeply crawl all tender listing pagination.
- Documents linked on fetched pages are downloaded within configured limits; their text is not parsed yet.
- Some sites depend on JavaScript, prohibit automated access, or require CAPTCHA. Do not bypass access controls.
- Do not treat all fetched pages as opportunities; extraction, verification, freshness and relevance scoring follow in Phase 2.
- Use `--max-pages`, `--max-documents` and `--delay` to control load. Respect each website's robots.txt and terms before expanding crawling.
- The Ollama settings are reserved for the next phase; scraping does not call the LAN model.

## Roadmap
1. Discovery foundation (current)
2. Source adapters (OCAC, CPPP and state portals) and structured RFP extraction
3. Local Ollama-powered relevance analysis and summaries
4. PostgreSQL, change tracking, nightly scheduling
5. FastAPI, UI, notifications and Docker


## VAF Marketing Intelligence dashboard (demo)

Install dependencies and launch the local UI from the project root:

~~~bash
git pull origin Dev_Guna
pip install -r requirements.txt
pytest -q
streamlit run dashboard.py
~~~

The dashboard opens at http://localhost:8501 (normally opened automatically by Streamlit).

Dashboard sections:
- Overview: real discovery, extraction, and AI pipeline counts
- Opportunities: AI-extracted tender details, scope, requirements, links, CSV and JSON exports
- Document queue: extracted PDFs and the ability to retry unfinished Ollama analysis
- Official listings: limited CAPTCHA-free CPPP homepage matches, with manual search link
- Diagnostics: real search, download, and model errors

The sidebar accepts a search topic and runs the existing pipeline in the background.
Click **Refresh runs** after it completes. Console output is written to
data/pipeline-ui.log, viewable in the sidebar.

If Ollama timed out after PDF extraction, select that run and click
**Retry unfinished documents** in **Document queue**, or use the terminal:

~~~bash
python retry_analysis.py \
  --run-dir data/runs/digilocker/YOUR_RUN_ID \
  --model qwen3:30b \
  --timeout 1200
~~~

This reuses already downloaded text, merging new AI results back into the existing
opportunities.json file without repeating web scraping or document downloads.

**Note:** None of the AI records or public homepage matches establish that a
tender is currently open. The original deadline is only a historical document fact;
the official tender detail page and corrigenda must be checked before bidding.
The dashboard is intended for a trusted local network; it has no authentication
or access control and should not be published on the internet.

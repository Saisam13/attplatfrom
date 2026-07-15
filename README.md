# MiniMines Sales Hub

Internal MiniMines sales support platform — one app for the whole sales team,
organised into modules (sidebar groups):

- **Trading** — the original ATT engine: upload EXIM (export-import) trade data
  xlsx files, run the 8-stage chemical trading attractiveness scoring pipeline,
  browse rankings and chemical dashboards, collect trader feedback that feeds
  back into scores, export workbooks and branded PDF reports.
- **Battery** — Battery Dashboard (categories, volumes and the price watch in
  one place) + Suppliers & Buyers procurement ranking with per-row add-as-lead.
- **EPR Intel** — upload the CPCB "EPR Targets for Producers" file (header row
  auto-detected), producers ranked by priority (target × w₁ + credits × w₂,
  weights in Settings), per-company **AI Sourcing Agent** (web search via
  Tavily/Firecrawl + extraction via Groq/Gemini/Claude: summary, potential
  math, contacts with proof URLs, news timeline), and an **EPR ↔ trade
  cross-link** showing the producer's actual EXIM shipments (also on Home).
- **HSN Explorer** — bundled open WCO Harmonized System directory (6,940 codes,
  `data/hsn_harmonized_system.csv`): search by code or keyword, AI "which code
  fits this product" suggestions, chapter → heading → subheading drill-down with
  every code badged **ours** (seen in uploaded shipments, with counts) vs
  **external** (directory only), per-code monthly trends + median price + ranked
  buyer/supplier lead lists, and a curated HSN ↔ product mapping table
  (chemical / battery / other, seedable from the latest run).
- **Leads** — universal tracker for all lead types (chemical / epr / battery /
  other), tagged by owner, type, stage (new → contacted → in talks → deal/dead)
  and free-form tags, with follow-up dates and a timestamped per-lead timeline
  (notes, stage changes, outreach, linked data snapshots). "+ Lead" buttons
  everywhere: EPR rows, HSN lead lists, battery suppliers/buyers.
- **Outreach** — AI-drafted personalized email / call script / WhatsApp message
  per lead (grounded in its linked data + EPR research; wa.me click-to-chat
  link), admin-managed pitch template library, and outreach logging onto the
  lead timeline. Sending stays manual.
- **Digest** — weekly in-app digest (pipeline activity, follow-ups due, hot EPR
  producers, ATT movers, battery price watch) + one-click branded PDF.

**External API** (`X-API-Key` header; keys generated/revoked on Settings):
`GET /api/v1/leads` (read-only leads incl. timelines + data snapshots, filters:
type/stage/owner/tag/updated_since) and the shared AI gateway
`POST /api/v1/ai/complete | search | research | match` so other internal tools
reuse the same providers and cache.

Identity is a no-password name picker (names stamp leads, feedback and settings
changes). An optional shared PIN can be enabled for internet-facing deployments
(`/api/v1/*` is exempt — it carries its own key auth).

## AI providers (all optional, free tiers work)

Settings → AI providers: **Groq** (free) + **Tavily** (free, 1000 searches/mo)
are enough to start; Gemini / Anthropic / Firecrawl are fallbacks in
configurable order. Keys are stored in the local DB. Everything AI-related
degrades gracefully when no key is set (clear error messages, rule-based
fallbacks where applicable).

All AI/search answers flow through the **unified cache** (`app_cache` table,
namespaced: llm_match, epr_research, web_search, ai_complete, ai_draft,
hsn_external) with per-namespace TTLs — inspect/clear per namespace on the
Settings page. The legacy `llm_cache` rows are migrated in automatically.

## Quick start

Double-click **`start.bat`** (or run it from a terminal). It will:
1. Create the Python venv and install dependencies (first run only)
2. `npm install` + build the React frontend if `frontend/dist` is missing
3. Start the server on `0.0.0.0:8000` and auto-restart it if it ever crashes

Then open `http://<your-lan-ip>:8000` on any device on the wifi (the LAN IP is
printed at startup).

- **Teammates (client install)**: send colleagues `ATT_Platform_Client_Setup.bat`
  (works from a network share / WhatsApp / email — it's standalone). They run it
  once, enter the server address, and get an "ATT Platform" icon on their
  Desktop and Start Menu (the icon is fetched from the server itself). The app
  icon also serves as the browser favicon and PWA manifest icon
  (`frontend/public/att-icon.ico|-192.png|-512.png`, regenerable via Pillow).
- **Development**: `dev.bat` (uvicorn `--reload` on :8000 + vite dev server on :5173).
- **Always-on office PC**: run `install_autostart.bat` **as administrator** once —
  the platform then starts on boot via Task Scheduler (`uninstall_autostart.bat` removes it).
- **Docker / cloud VM**: `docker build -t att-platform .` then
  `docker run -p 8000:8000 -v att_data:/app/data att-platform`.
  For anything internet-facing: enable the PIN on the Settings page and put the
  container behind HTTPS (e.g. Caddy/nginx or a cloud load balancer).

## Pages

1. **Dashboard** (landing) — KPI tiles, top 10 by ATT, biggest movers vs the
   previous run, export shortcuts (workbook / PDF / battery workbook).
2. **Upload & Runs** — drag-drop EXIM `.xlsx` files (row 1 title, row 3 headers,
   data from row 4), optional replacement base portfolio (needs a
   `Category Overview` sheet like the bundled Scimplify base), trend-exclusion
   months. Run history with live progress, rename, delete, and per-run exports.
3. **Rankings** — three tabs (All / Base portfolio / Opportunity map), sortable
   virtualized table for large pools, column show/hide (remembered per browser),
   score heat-coloring, CSV export of the filtered view, Confirm / Challenge /
   Correct feedback buttons. The `Fb adj` column shows the bounded (±5)
   trader-feedback adjustment baked into ATT.
4. **Chemical detail** — radar chart, shipment + median-price monthly charts,
   price stats, clickable buyers/suppliers (drill into raw shipment rows),
   geo anomalies, regulatory status, and ATT history across runs.
5. **Battery Procurement** — separate upload slot for battery-scrap EXIM data.
   Rows are classified into feedstock categories (Black Mass, Li-ion / Lead-acid /
   mixed battery scrap, electrode scrap, spent catalyst, NdFeB magnet scrap,
   e-waste/PCB, residues/tailings). Suppliers are ranked by procurement
   attractiveness (volume 30%, price competitiveness 25%, consistency 20%,
   reliability 15%, geography 10%); a second tab ranks the competing buyers.
   Categories tab shows per-category market stats + monthly trends; exports its
   own workbook.
6. **Run Compare** — pick two runs → gainers/losers by ATT delta with rank and
   tier changes, plus chemicals new to / dropped from the current run.
7. **Raw Data** — every parsed EXIM row with match type (direct / llm / near /
   none), score, counterparties, filters, and pagination.
8. **Geo Anomalies** — run-wide list of >2σ volume anomalies correlated with the
   geopolitical events database.
9. **Feedback** — all entries for the run + xlsx export (page can be hidden in
   Settings; the buttons stay).
10. **Settings** — everything below, with a change log (who / when / old → new):
    - **LLM matching**: provider (Anthropic / Gemini / Ollama / off), API key,
      model, test-connection button. No restart needed.
    - **Scoring weights & tier cutoffs** with a **live impact preview** against
      the active run before saving (applies to future runs).
    - Default trend-excluded months.
    - **Retention**: auto-delete runs older than N days (0 = keep forever).
    - **Feedback adjustment** on/off, Feedback page visibility.
    - **Security**: shared-PIN gate for internet-facing deployments.

## Feedback → score loop

Confirm +1, Challenge −2, Correct ±2.5 toward the suggested tier — summed per
chemical across all past runs, clamped to ±5, and added to ATT in *future* runs
(shown transparently in the `Fb adj` column and the PDF). Disable in Settings.

## LLM-assisted matching (default off)

Configure on the Settings page (stored in the DB; `config.json` values are used
as seed defaults for fresh installs). In HYBRID mode, rule-based fuzzy matching
runs first; only descriptions scoring below the 60% direct threshold are sent to
the LLM (batched, with the base chemical list in the prompt). Answers are cached
in SQLite (`llm_cache`), so repeat descriptions are never re-sent. Provider off
or no key → pure rule-based, identical numbers to the original `trading_module.py`.

Defaults: anthropic → `claude-sonnet-5` (use `claude-haiku-4-5-20251001` for
cheap), gemini → `gemini-2.5-flash`, ollama → whatever local model you set.

## Exports

- **9-tab ATT workbook** — Rankings, Price Deep Dive, Buyer Intel, Supplier
  Intel, Time Trends, Opportunity Map, India Incentives, Regulatory + Geo Log,
  Raw Parsed Data.
- **PDF summary report** — 2-3 page MiniMines-branded management summary (KPIs,
  top 15, movers, opportunities, methodology).
- **Battery workbook** — Suppliers, Buyers, Categories, Monthly Trends, Raw Data.
- **Feedback workbook** and **CSV of any filtered Rankings view**.

## Changing the port

Edit the `--port 8000` in `start.bat` (and `dev.bat` + `frontend/vite.config.ts`
proxy target for dev mode).

## Data locations

- `data/att.db` — SQLite database (runs, scores, trends, logs, raw rows,
  feedback, battery entities, EPR companies + research, HSN directory + product
  map, leads + lead events, pitch templates, API keys, unified cache,
  settings + settings log)
- `data/uploads/<run_id>/` — uploaded files + generated exports per run
- `data/default_base_portfolio.xlsx` — bundled 260-chemical base portfolio
- `data/hsn_harmonized_system.csv` — bundled open WCO HS directory (re-import
  via `POST /api/hsn/import`)

Locked/unreadable xlsx files (e.g. OneDrive locks) are skipped with a message in
the run stats rather than failing the run.

## Architecture

- **Backend**: FastAPI monolith (`backend/`), pipelines run in worker threads
  with progress polled from the `runs` table (kind = `chemical` | `battery`).
  Chemical pipeline logic ported 1:1 from `trading_module.py` v2.0
  (`backend/pipeline/engine.py`), battery procurement pipeline in
  `backend/pipeline/battery.py`, exports in `export.py` / `battery_export.py`,
  PDF in `backend/report.py` (reportlab), settings store in `backend/settings.py`.
  Sales modules are APIRouter files: `epr.py` (parser + priority + sourcing
  agent + trade cross-link, ported from the eprintelligence PHP app), `hsn.py`,
  `leads.py` (incl. `/api/v1/leads` + API keys), `outreach.py`, `digest.py`,
  `ai_api.py` (`/api/v1/ai/*`). Shared services: `ai.py` (provider-routed
  completion: Groq/Gemini/Anthropic/Ollama with fallback), `research.py`
  (Tavily/Firecrawl search + company research prompt), `cache.py` (unified
  namespaced cache).
- **DB**: SQLite via SQLAlchemy (`backend/db.py`) with additive column
  migrations on startup. Swap the URL for Postgres if concurrent use grows.
- **Frontend**: React + Vite + TypeScript + recharts (`frontend/`), MiniMines
  dark navy/teal theme (palette from m-mines.com), served as static files by
  FastAPI on the same port.

# Maintenance Plan Builder — Claude Code Context

## Purpose
POC demonstrating automated packaging of FMECA maintenance tasks into SAP PM master data structures. Replaces manual Crystallize workflow (40–50 contractors, weeks of effort) with a configurable rules engine + human-in-the-loop refinement.

## Repository Layout
- `app.py` — Streamlit entry point, 4-tab navigation
- `config.py` — constants, env var loading
- `db/models.py` — SQLAlchemy ORM (4 domains)
- `db/database.py` — session factory (SQLite default, PG via DATABASE_URL)
- `db/loader.py` — parse FMECA Excel → normalised DB rows
- `db/seed/default_rules.json` — LNG Train Standard rule set
- `engine/packager.py` — core packaging algorithm
- `engine/rules.py` — one evaluator class per rule_type
- `ui/page_ingest.py` — Step 1: upload, asset tree, stats
- `ui/page_rules.py` — Step 2: rule card editor, estimated output
- `ui/page_review.py` — Step 3: plan tree + detail panel, move/split
- `ui/page_export.py` — Step 4: format picker, download
- `export/excel_writer.py` — SAP Data Mate staging workbook
- `Data/` — sample Excel dataset (already present)
- `architecture/` — ERD and mockup (already present)

## Running
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Key Design Decisions
- All rule logic isolated in `engine/rules.py` — new rule = new evaluator class
- `DATABASE_URL` env var switches SQLite ↔ PostgreSQL with no code changes
- `db/seed/default_rules.json` for new rule sets without touching Python
- UI pages are independent modules
- `session_id` (UUID) tags each packaging run so multiple runs coexist in DB

## Data Flow
FMECA Excel → loader.py → DB (FunctionalLocation, FailureMode, Task)
Rules (DB/JSON) → packager.py → DB (MaintenancePlan, Item, TaskList, Operation)
DB → page_review.py → user refinement → page_export.py → Excel/CSV/JSON

## Deployment
- Hosted on **Streamlit Community Cloud**, auto-deploys from `main` branch on GitHub
- Repo: https://github.com/johannvis/woodside-maintenance-plan-builder
- To deploy a change: commit to `main` and push — Streamlit Cloud picks it up automatically within ~1 minute
- Note: the GitHub repo name still contains "woodside" (rename via GitHub Settings → Repository name if needed)
- No CI/CD pipeline — deployment is purely git push → Streamlit Cloud webhook
- SQLite DB is ephemeral on Streamlit Cloud — resets on every redeployment; demo always starts from a fresh DB
- **Live app URL: https://maint-plan-build.streamlit.app**

## Working Style
- When asked to implement something ("can you do it?"), go all the way: write code → commit → push, without stopping mid-task to ask for confirmation
- Don't ask "want me to commit now?" after already writing all the code — the commit is less consequential than the code changes themselves

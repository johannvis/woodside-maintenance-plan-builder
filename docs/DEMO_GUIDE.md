# Maintenance Plan Builder — Demo Guide

**Audience:** Parth, Jason, Emma
**Duration:** ~15 minutes
**URL:** http://localhost:8501 (after installation)

---

## The Problem (2 minutes)

Open with this framing:

> "The operator currently uses 40–50 contractors running a tool called Crystallize to manually package FMECA maintenance tasks into SAP PM master data structures. The packaging step is entirely rule-based — things like 'group mechanical tasks at the same interval, up to 8 hours per task list.' Crystallize has no incentive to automate it, so it stays manual. This POC shows we can automate it in seconds, with a configurable rules engine and a human-in-the-loop review step."

---

## Step 1 — Ingest & Preview (3 minutes)

1. Open the app at http://localhost:8501
2. You'll land on **Tab 1: Ingest & Preview**
3. Click **"Load LNG Train Sample"**
4. Point out the five stats chips that appear:
   - **1,000 tasks** | **125 FLOCs** | **14 Asset Classes** | **10 Systems** | **1 Train**
5. Expand the asset tree:
   `🏭 LNG1 → ⚙️ Feed Gas Compression → 📦 Feed Gas Compressor A`
6. Click on a sub-system — a table of tasks appears on the right
7. Scroll down to show the three distribution charts (task type, resource type, criticality)

**Key message:**
*"The tool ingests any FMECA workbook — this one has 1,000 tasks. In a real engagement this step replaces hours of manual data prep."*

---

## Step 2 — Rule Editor (3 minutes)

1. Click **Tab 2: Rule Editor**
2. Walk through the four rule cards:

   | Rule | What it means |
   |------|--------------|
   | **Primary Grouping** | Which level of the asset hierarchy to group tasks by (Train → System → Sub-system → Equipment). Default: Sub-system (level 3). |
   | **Max Duration Cap** | Split a task list if total duration exceeds this many hours. Default: 8 hrs. |
   | **Shutdown Separation** | Keep online tasks and shutdown tasks in separate plan items. |
   | **Regulatory Isolation** | Give statutory/regulatory tasks their own dedicated plan items. |

3. **Live demo:** Change "Max Hours per Item" from **8 → 4**, click **"Refresh Estimate"**
   - Item count roughly doubles — more splits required to stay under cap
   - Change it back to 8
4. Show the Plan Naming Prefix field (`PM-LNG`)

**Key message:**
*"A planner can tune these rules through the UI — no code changes needed. Different asset classes or client standards just mean different rule values."*

---

## Step 3 — Review & Refine (5 minutes)

1. Click **Tab 3: Review & Refine**
2. Click **"▶ Generate Plans"** (takes 2–3 seconds)
3. Point out the summary bar:
   - **270 plans** | **856 items** | **856 task lists** | **1,000 operations**
4. Expand a plan in the tree on the left, e.g.:
   `📋 PM-LNG-Feed Gas Compressor A-PG-MECH-001`
5. Click on an item (green = online, yellow = shutdown, red = regulatory)
6. On the right panel, show:
   - **Badges** — frequency, duration, online/shutdown/regulatory status
   - **Duration bar** — visual indicator vs the 8-hour cap
   - **Operations list** — the individual maintenance tasks packaged into this item
   - **FMECA Traceability table** — links each operation back to its original failure mode and criticality

7. **Human-in-the-loop demo:** Use the "Move Operation to Another Item" dropdown to move one operation to a different item, then click **Move**. The duration bar updates.

**Key message:**
*"The algorithm does 90% of the work in seconds. The planner reviews the output and makes targeted adjustments — rather than building every plan from scratch."*

---

## Step 4 — Export (2 minutes)

1. Click **Tab 4: Export**
2. Leave format as **"Data Mate Staging (.xlsx)"**
3. Show the include checkboxes — everything is ticked by default including FMECA traceability and rule audit
4. Point out the **preview table** (first 20 rows of the flat output)
5. Click **"⬇️ Download Data Mate Staging (.xlsx)"**
6. Open the downloaded file in Excel — show the four sheets:
   - **Maintenance Plans** — plan/item structure with frequency and duration
   - **Task Lists** — one row per task list
   - **Operations** — the packaged task steps
   - **FMECA Traceability** — audit trail back to the source failure modes

**Key message:**
*"The output is formatted for SAP Data Mate — it can go straight to the upload queue. The rule audit sheet gives you a full record of what packaging logic was applied."*

---

## Closing (1 minute)

> "What you've just seen took about 10 seconds to run. The manual equivalent in Crystallize takes a team of contractors several weeks. The rules are configurable, the output is SAP-ready, and every decision is traceable back to the FMECA. This same pattern could be extended to any asset class — LNG, pipelines, utilities — just by loading a different FMECA and adjusting the rules."

**Potential follow-up questions:**

| Question | Answer |
|----------|--------|
| Can it handle real client data? | Yes — upload any FMECA workbook on Tab 1. The column mapper handles common naming variations automatically. |
| What about edge cases the rules don't cover? | The review step (Tab 3) is specifically for that — planners can move individual operations between items. |
| How would we deploy this? | Docker container on EC2, same pattern as the MainStream demo. Or Streamlit Community Cloud for quick sharing. |
| Can we add more rules? | Yes — each rule type is an isolated class in `engine/rules.py`. Adding a new rule = adding one class. |

---

*Demo prepared by Johann Visser — April 2026*

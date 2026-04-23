# Maintenance Plan Builder — Demo Guide

**Audience:** Parth, Jason, Emma
**Duration:** ~20 minutes

---

## The Problem (2 minutes)

Open with this framing:

> "The operator currently uses 40–50 contractors running a tool called Crystallize to manually package FMECA maintenance tasks into SAP PM master data structures. The packaging step is entirely rule-based — things like 'group mechanical tasks at the same interval, up to 8 hours per task list.' Crystallize has no incentive to automate it, so it stays manual. This POC shows we can automate it in seconds, with a configurable rules engine and a human-in-the-loop review step."

---

## Step 1 — Ingest & Preview (3 minutes)

1. Open the app and land on **Tab 1: Ingest & Preview**
2. Click **"Load LNG Train Sample"**
3. Point out the five stats chips that appear:
   - **1,000 tasks** | **125 FLOCs** | **14 Asset Classes** | **10 Systems** | **1 Train**
4. Expand the asset tree:
   `🏭 LNG1 → ⚙️ Feed Gas Compression`
5. Click the **"View all N tasks"** roll-up button at the system level — this shows all tasks across every piece of equipment in that system in one hit
6. Drill down to a leaf node e.g. `📦 Feed Gas Compressor A` and click it — the task table updates on the right
7. Scroll down to show the three distribution charts (task type, resource type, criticality)

**Key message:**
*"The tool ingests any FMECA workbook — this one has 1,000 tasks. In a real engagement this step replaces hours of manual data prep."*

---

## Step 2 — Rule Editor (4 minutes)

1. Click **Tab 2: Rule Editor**
2. Walk through the seven rule cards:

   | Rule | What it means |
   |------|--------------|
   | 🌲 **Primary Grouping** | Which level of the asset hierarchy to group tasks by (Train → System → Sub-system → Equipment). Default: Sub-system (level 3). |
   | ⏱️ **Max Duration Cap** | Split a task list if total duration exceeds this many hours. Default: 8 hrs. |
   | 🔒 **Shutdown Separation** | Keep online tasks and shutdown tasks in separate plan items. |
   | 📋 **Regulatory Isolation** | Give statutory/regulatory tasks their own dedicated plan items. |
   | 🔧 **Task Type Separation** | Separate tasks by type (Inspection, Lubrication, PM, CM) into distinct items. |
   | 🔴 **Criticality Isolation** | Isolate A-class/HIGH criticality tasks into their own dedicated items. |
   | 🔢 **Max Operations per Item** | Cap the number of operations per task list and split if exceeded (0 = disabled). |

3. **Live demo:** Change "Max Hours per Item" from **8 → 4**, click **"Refresh Estimate"**
   - Item count roughly doubles — more splits required to stay under cap
   - Change it back to 8
4. Show the Plan Naming Prefix field (`PM-LNG`)

**Key message:**
*"A planner can tune these rules through the UI — no code changes needed. Different asset classes or client standards just mean different rule values."*

---

## Step 3 — Review & Refine (7 minutes)

1. Click **Tab 3: Review & Refine**
2. Click **"▶ Generate Plans"** (takes 2–3 seconds)
3. Point out the summary bar:
   - **270 plans** | **856 items** | **856 task lists** | **1,000 operations**

### Plan View (default)

4. Expand a plan in the tree on the left, e.g.:
   `📋 PM-LNG-Feed Gas Compressor A-PG-MECH-001`
5. Click on an item (green = online, yellow = shutdown, red = regulatory)
6. On the right panel, show:
   - **Badges** — frequency, duration, online/shutdown/regulatory status
   - **Duration bar** — visual indicator vs the 8-hour cap
   - **Operations list** — the individual maintenance tasks packaged into this item
   - **FMECA Traceability table** — links each operation back to its original failure mode and criticality
7. **Human-in-the-loop demo:** Use the "Move Operation to Another Item" dropdown to move one operation to a different item, then click **Move**. The duration bar updates.

### Pending Agent Actions queue (after AI Review)

If AI Review has been run, a **"🤖 Pending Agent Actions"** panel appears at the top of Plan View showing every non-keep recommendation awaiting action:

- **🔗 Merge** items have a **✓ Apply** button — one click moves all operations to the agent-nominated target, re-numbers them, and updates durations. No manual intervention needed.
- **✂️ Split** and **🏷️ Reclassify** items have a **🔍 Review** button — jumps directly to that item in the plan tree so the planner can inspect and act.
- **✕ Dismiss** removes any item from the queue without applying it.
- **Apply All Merges** and **Dismiss All** bulk controls for processing the full queue quickly.

*This is the human-in-the-loop approval gate: agents recommend, planner approves.*

### Equipment View

8. Switch the **View Mode** toggle to **Equipment View**
9. Click any FLOC in the hierarchy — the panel shows all operations assigned to that asset across all plans, regardless of which plan they landed in
10. This is useful for verifying that a piece of equipment's full maintenance load looks sensible

### Packaging Trace

11. Switch to **Packaging Trace**
12. This is a flat, filterable table that maps every one of the 1,000 FMECA tasks to its assigned plan and item
13. Filter by plan name or FLOC to audit specific decisions

### AI Insights

14. Click **"✨ Generate AI Insights"**
15. Claude Haiku analyses the packaging output and surfaces benchmark observations — e.g. items running close to the duration cap, regulatory task concentration, items with unusually high operation counts

**Key message:**
*"The algorithm does 90% of the work in seconds. The planner has three lenses — Plan View (with agent action queue), Equipment View for asset-centric checks, and Packaging Trace for full auditability. Merge recommendations execute in one click; split and reclassify go to the human for final call."*

---

## Step 4 — AI Review (5 minutes)

1. Click **Tab 4: AI Review**
2. Expand **"⚙️ Agent Configuration"** — show the six specialist agent tabs and the Judge weight sliders
3. Leave defaults and click **"▶ Run AI Review"**
4. Point out the live streaming feed as items are processed in parallel
5. After completion, show the summary metrics: Kept / Split / Merged / Reclassified counts
6. Switch back to **Tab 3 → Plan View** — items reviewed by AI now show a **🤖 badge**
7. Click a badged item and expand the **"🤖 Agent Review"** section in the right panel:
   - Six coloured score bars (one per agent)
   - Judge decision + rationale

### What each agent is looking for

| Agent | Focus |
|-------|-------|
| 🔒 **Safety** | Regulatory tasks properly isolated; A-class FMs at correct frequency; no unsafe online/shutdown mixing |
| 💰 **Cost** | Over-splitting penalty; single-operation items that should be merged; bundling opportunity with same resource/interval |
| ⚡ **Efficiency** | Shutdown tasks consolidated; online maintenance maximised; interval aligned to plant windows |
| 🔩 **Integrity** | A-class failure modes traceable and at correct frequency; B/C-class not diluting A-class items |
| 📋 **Coverage** | All disciplines (MECH, ELEC, INST…) and task types present in source FMECA are represented across the plan |
| 🗺️ **Route** | Same trade + same L3 area + same interval = one walk-around route; flags unnecessary fragmentation |

The **⚖️ Judge** is invoked only when agents disagree. It applies configurable weights (Safety 35% / Integrity 25% / Efficiency 20% / Cost 20%) to make a final call: keep, split, merge, or reclassify.

**Key message:**
*"This replicates the multi-discipline deliberation that 40–50 contractors previously brought to the packaging review. Six perspectives, in parallel, in seconds. The planner can tweak any agent's prompt and click 'Clear & Re-run' to iterate — no code changes needed."*

### Iterative refinement

8. Click **"⚙️ Agent Configuration"**, edit a system prompt (e.g. make the Cost agent more aggressive about merging), click **💾 Save**
9. Click **"🔄 Clear & Re-run"** — this wipes the previous decisions and runs fresh with the updated prompts
10. Compare results — the Pending Actions queue in Tab 3 updates automatically to reflect the new decisions

---

## Guided Walk-Through: Agent Review → Merge Execution (on sample data)

This is the highest-impact sequence to run on the LNG Train sample. It demonstrates the full advisor → executor loop in under 3 minutes.

### Setup (do this before the demo)

Use these rule settings to generate a plan structure that produces interesting agent recommendations:
- **Primary Grouping:** Sub-system (Level 3) — default, keep as-is
- **Max Duration Cap:** 8 hrs — default
- All other rules: defaults

This produces ~856 plan items from 1,000 tasks. Because tasks are grouped at the equipment level, the **Feed Gas Compression** system (C01, 246 tasks) ends up with many small single-operation items — exactly the pattern the Cost and Route agents are designed to flag.

### The specific path to follow

**1. Load & package**
- Tab 1 → **Load LNG Train Sample** → confirm 1,000 tasks / 125 FLOCs
- Tab 3 → **▶ Generate Plans** → confirm ~856 items

**2. Run a focused AI Review**
- Tab 4 → set **Max items to review** to **30** (saves time and API cost for the demo)
- Click **▶ Run AI Review** — watch the streaming feed
- After completion, note the Merged count — with the default rules producing many single-op items, expect several merge recommendations

**3. Go to the Pending Actions queue**
- Switch to **Tab 3 → Plan View**
- The **🤖 Pending Agent Actions** panel appears at the top
- Find a **🔗 MERGE** row — look for one in the **Feed Gas Compression** area (C01), MECH-ROT trade, 12-monthly interval

**4. Read the queue row — point out three things**
- The **agent vote summary** (e.g. `💰🗺️ → merge  🔒🔩 → keep`) — shows which agents agreed and which dissented
- The **merge target** line (`→ into: <target item name>`) — exactly where the operations will land
- The **rationale snippet** — the Judge's one-line explanation

**5. Apply the merge**
- Click **✓ Apply** on one row — watch the success toast: `"Merged: 2 ops → <target item>"`
- Or click **✓ Apply All N Merge Recommendations** to execute the whole queue at once
- The row disappears from the queue; the source item is now empty

**6. Verify the result**
- Find the target item in the plan tree (use the name from the merge target line)
- Click it — the Operations list now shows the combined set, re-numbered (010, 020, 030…)
- The Duration bar reflects the updated total

### Why this sequence lands

> *"The rules engine did its job — it packaged 1,000 tasks in 3 seconds following the client's rules. Then six AI agents reviewed the output from different perspectives. The Route agent saw that a mechanical technician would need three separate trips to the same compressor area for three separate plan items — all same trade, same interval, same physical location. The Cost agent flagged the same items as inefficient overhead. Four of six agents agreed: merge. One click executed it. That's the 40-contractor deliberation, automated."*

---

## Step 5 — Export (2 minutes)

1. Click **Tab 5: Export**
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

## Bonus — Algorithm Explainer (optional, 2 minutes)

1. Click **Tab 7: ⚙️ Algorithm**
2. Walk through the 9-step packaging logic — useful if the audience wants to understand what's happening under the hood or discuss customisation

---

## Closing (1 minute)

> "What you've just seen took about 10 seconds to run. The manual equivalent in Crystallize takes a team of contractors several weeks. The rules are configurable, the AI review replicates multi-discipline expert deliberation, the output is SAP-ready, and every decision is traceable back to the FMECA. This same pattern could be extended to any asset class — LNG, pipelines, utilities — just by loading a different FMECA and adjusting the rules."

**Potential follow-up questions:**

| Question | Answer |
|----------|--------|
| Can it handle real client data? | Yes — upload any FMECA workbook on Tab 1. The column mapper handles common naming variations automatically. |
| What about edge cases the rules don't cover? | The review step (Tab 3) is specifically for that — planners can move individual operations between items. The AI Review flags the same issues automatically and queues them for one-click action. |
| How would we deploy this? | Currently live on Streamlit Community Cloud. Production deployment would be a Docker container on EC2 with a PostgreSQL database for persistence. |
| Can we add more rules? | Yes — each rule type is an isolated class in `engine/rules.py`. Adding a new rule = adding one class. |
| Can we add more agents? | Yes — each agent is a class in `engine/agents/`. Adding a new perspective = adding one class and a row in the default_agents seed file. |
| What's the AI Insights feature doing? | Claude Haiku is called via the Anthropic API against the packaging output. It's a lightweight analytical layer — not making packaging decisions, just surfacing patterns for the planner. |
| What does the Route agent actually check? | It uses the FLOC L3 sub-system hierarchy as a spatial proxy — equipment under the same L3 node is physically co-located. The agent flags cases where the same trade would need multiple separate trips to the same area. |

---

*Demo prepared by Johann Visser — April 2026*

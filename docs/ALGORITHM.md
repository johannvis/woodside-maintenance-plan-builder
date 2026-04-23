# Packaging Algorithm — How Tasks Become SAP PM Structures

This document explains the step-by-step logic `engine/packager.py` uses to convert raw FMECA tasks into Maintenance Plans, Plan Items, Task Lists, and Operations.

---

## Overview

```
FMECA Tasks (flat list)
        │
        ▼
  [Step 1] Regulatory isolation
        │
        ├── Regulatory tasks ──────────────────────────────────────────┐
        │                                                               │
        ▼                                                               ▼
  [Step 2] Group by FLOC level            [Steps 3–7 also applied separately]
        │
        ▼
  [Step 3] Separate online / shutdown
        │
        ▼
  [Step 4] Criticality isolation (optional)
        │
        ▼
  [Step 5] Split by resource type (MECH / INST / ELEC …)
        │
        ▼
  [Step 6] Split by task type (OT / FT / PM …) — optional
        │
        ▼
  [Step 7] Split by maintenance interval (3-months / 6-months …)
        │
        ▼
  [Step 8] Max-duration cap (split bucket if total hours > cap)
        │
        ▼
  [Step 9] Max-operations cap (split bucket if operation count > cap)
        │
        ▼
  Each bucket → 1 MaintenancePlanItem + 1 TaskList + N Operations
  Buckets sharing the same (FLOC, resource type) → grouped under 1 MaintenancePlan
```

---

## Step-by-Step Detail

### Step 1 — Regulatory Isolation
*Rule: `regulatory_isolation` (default: enabled)*

All tasks flagged `is_regulatory = True` are pulled into a separate stream and processed independently through Steps 2–9. This ensures regulatory/statutory tasks always live in their own dedicated Plan Items — they never share a Task List with routine maintenance tasks.

If `regulatory_isolation` is disabled, all tasks are treated as a single stream.

---

### Step 2 — Group by Hierarchy Level
*Rule: `grouping_level` (default: 3 = Sub-system)*

Each task is mapped to its ancestor FunctionalLocation at the configured level:

| Level | Meaning | Example |
|-------|---------|---------|
| 1 | Train | LNG Train 1 |
| 2 | System | Feed Gas Compression |
| 3 | Sub-system (default) | Feed Gas Compressor A |
| 4 | Equipment | Compressor Inlet Scrubber |

All tasks under the same FLOC node at this level are candidates to share a plan. Raising the level (e.g. from 3 → 2) makes plans larger (more operations per item) because a wider group of assets is combined.

---

### Step 3 — Online / Shutdown Separation
*Rule: `shutdown_separation` (default: enabled)*

Tasks requiring a plant shutdown (`is_online = False`) are placed in separate Plan Items from tasks that can be performed while the plant is running. A planner executing an online task should never need to trigger a shutdown — so this split prevents accidental co-scheduling.

---

### Step 4 — Criticality Isolation
*Rule: `criticality_isolation` (default: disabled)*

When enabled, tasks associated with A-class (safety-critical) failure modes are isolated into their own Plan Items, separate from B/C-class tasks. Useful when A-class tasks require a different approval or sign-off workflow.

---

### Step 5 — Resource Type Split
*Always active*

Tasks are split by the `resource_type` field (MECH, INST, ELEC, etc.). A mechanical technician's work order should not contain instrumentation tasks — this split ensures each Task List is executable by a single trade.

---

### Step 6 — Task Type Separation
*Rule: `task_type_separation` (default: disabled)*

When enabled, tasks are further split by their `task_type` code (e.g. OT = On-condition Task, FT = Functional Test, PM = Preventive Maintenance). Useful when different task types require different Work Order types in SAP.

---

### Step 7 — Interval Split
*Always active*

Tasks within the same FLOC / online-flag / resource / task-type bucket are finally split by maintenance interval (e.g. `3-months` vs `6-months`). Tasks with different intervals cannot share a Plan Item because a Plan Item has exactly one frequency.

---

### Step 8 — Max-Duration Cap
*Rule: `max_duration` (default: 8 hours)*

If the tasks in a bucket would exceed the duration cap when summed, the bucket is split into sub-buckets. Tasks are assigned greedily (first-fit) — a new sub-bucket starts whenever adding the next task would breach the cap.

This prevents any single Task List from requiring more hours than a standard maintenance shift.

---

### Step 9 — Max-Operations Cap
*Rule: `max_operations` (default: 0 = disabled)*

When enabled, a bucket is further split if it contains more than N operations. Useful for SAP systems that have a hard limit on the number of operations per Task List.

---

## Plan Naming

After bucketing, tasks are assembled into ORM objects:

- **MaintenancePlan** — one per `(FLOC, resource_type)` pair
  Name: `{prefix}-{floc_name}-{resource_type}-{seq:03d}`

- **MaintenancePlanItem** — one per bucket
  Description encodes the key attributes: FLOC | resource | interval | ONLINE/SHUTDOWN | REG/CRIT

- **TaskList** — one per Plan Item

- **Operation** — one per source task, numbered in multiples of 10 (010, 020, …)

---

## Why Plans Have Mostly One Operation

With the default rules (grouping at level 3, by resource and interval), each leaf FLOC typically has only 1–2 tasks per trade per interval — resulting in many single-operation plan items. To produce richer multi-operation plans:

1. **Raise the grouping level** to 2 (System) — combines all equipment within a system under one plan
2. **Disable task type separation** — keeps OT and FT tasks together
3. **Disable criticality isolation** — keeps A and B-class tasks together

These can all be adjusted live in the Rule Editor without touching code.

---

## AI Review — Multi-Agent Analysis

After the rules engine produces a draft plan, six specialist AI agents review each plan item in parallel and a judge agent arbitrates disagreements.

```
Draft MaintenancePlan (from packager.py)
        │
        ▼
AgentOrchestrator — for each MaintenancePlanItem:
        ├─ 🔒 Safety Agent      → score (0–10) + action + rationale
        ├─ 💰 Cost Agent        → score (0–10) + action + rationale
        ├─ ⚡ Efficiency Agent  → score (0–10) + action + rationale
        ├─ 🔩 Integrity Agent   → score (0–10) + action + rationale
        ├─ 📋 Coverage Agent    → score (0–10) + action + rationale
        └─ 🗺️ Route Agent       → score (0–10) + action + rationale
                │
                ▼
        Majority consensus? ─── Yes ──→ action accepted (keep/split/merge/reclassify)
                │
               No
                │
                ▼
        ⚖️ Judge Agent → weighted arbitration → final action
        │
        ▼
AgentDecision + JudgeDecision records stored in DB
        │
        ▼
🤖 badges + score bars shown in Plan View (Tab 3)
```

### Specialist Agents

Each agent is a focused reviewer with a domain-specific system prompt, configurable via the **⚙️ Agent Configuration** panel in Tab 4.

| Agent | Core question | Key signals |
|-------|--------------|-------------|
| 🔒 **Safety** | Are compliance tasks isolated? Are critical FMs at the right frequency? | `is_regulatory`, `criticality`, `is_online` |
| 💰 **Cost** | Are similar tasks bundled to minimise travel and setup overhead? | `resource_type`, `total_duration_hours`, adjacent items |
| ⚡ **Efficiency** | Are shutdown tasks consolidated? Is online maintenance maximised? | `is_online`, `interval`, item count |
| 🔩 **Integrity** | Are A-class FMs traceable and at the correct frequency? | `criticality`, `failure_mode`, `interval` |
| 📋 **Coverage** | Are all disciplines and task types from the FMECA represented in the plan? | `all_disciplines_in_floc`, `disciplines_covered_by_other_items` |
| 🗺️ **Route** | Would the same trade need multiple trips to the same physical area? | `floc_hierarchy` L3, `same_area_same_resource_items` |

### Context Passed to Each Agent

Every agent receives the same rich context for the item under review:

- Operations list (description, duration, resource, materials)
- Source task data (failure mode, criticality, task type, is_online, is_regulatory)
- FLOC hierarchy (L1 → L4 names) for spatial reasoning
- Adjacent items in the same plan (for merge/split suggestions)
- Cross-plan context: all other items in the same L3 area with the same resource and interval (route fragmentation signal)
- Coverage context: all disciplines present across the whole FLOC vs. those covered by other items

Agents use Anthropic tool-use to return structured JSON — score, recommended action, and rationale — not free text.

### Consensus and Judge

- **Consensus rule:** if ≥ 4 of 6 agents recommend the same action → accepted without judge
- **Judge invoked:** when no single action has majority support
- **Judge model:** `claude-sonnet-4-6` (more reasoning capacity than the specialist Haiku agents)
- **Judge weights (configurable):** Safety 35% · Integrity 25% · Efficiency 20% · Cost 20%
- Safety and integrity concerns override cost and efficiency — an unsafe plan is never acceptable regardless of cost savings

### Iterative Refinement

The agent prompts and weights are fully editable from the UI. After editing, **🔄 Clear & Re-run** deletes the previous decisions for the current packaging session and re-runs from scratch. No re-packaging required — the draft plan is preserved and only the AI review layer is refreshed.

---

## Pending Actions Queue & Plan Mutator

After the AI review completes, non-keep decisions are surfaced in the **"🤖 Pending Agent Actions"** panel at the top of the Plan View (Tab 3). This is the human-in-the-loop approval gate between agent recommendation and plan change.

```
AgentDecision + JudgeDecision (DB)
        │
        ▼
Pending Actions Queue (page_review.py)
  ├─ 🔗 Merge    → ✓ Apply  ──→ engine/plan_mutator.apply_merge()
  ├─ ✂️ Split    → 🔍 Review ──→ jump to item in plan tree (manual)
  ├─ 🏷️ Reclassify → 🔍 Review ──→ jump to item in plan tree (manual)
  └─ ✕ Dismiss  → mark JudgeDecision.modified = True (remove from queue)
```

### What each action does

| Action | Automated? | What happens |
|--------|-----------|-------------|
| **Merge** | ✅ Full auto | All operations from source item moved to agent-nominated target. Operation numbers re-sequenced. Duration totals updated on both items. `JudgeDecision.modified = True`. |
| **Split** | ⬜ Manual | Queue routes planner to the item. Planner uses "Move Operation" controls to split manually. Future: auto-split once agents specify the operation partition. |
| **Reclassify** | ⬜ Manual | Queue routes planner to the item for interval/type adjustment. Future: auto-apply once agents output the new classification values. |
| **Keep** | N/A | Never appears in queue. No action required. |

### Merge target resolution

When applying a merge, the mutator queries all `AgentDecision` rows for the source item where `recommended_action = "merge"` and `target_item_id IS NOT NULL`. The most-nominated `target_item_id` wins (majority vote across agents). If no agent specified a target, the apply fails gracefully with an error message and the item stays in the queue for manual review.

### Bulk controls

- **Apply All Merges** — applies every merge in the queue in sequence
- **Dismiss All** — marks all pending decisions as dismissed without applying
- Applied and dismissed items vanish from the queue immediately

### Path to full autonomous execution

Merge is fully executable today because the target is unambiguous (an item ID). Split and reclassify require richer agent output before they can auto-execute:

- **Split** needs: which operation IDs go to group A vs. group B (extend agent tool-use schema with `split_spec`)
- **Reclassify** needs: the new interval, frequency unit, or classification values (extend schema with `reclassify_spec`)

Once those schema extensions are in place, the mutator gains `apply_split()` and `apply_reclassify()` — and the queue becomes fully executable without human intervention for high-confidence decisions.

---

*Rules engine: `engine/packager.py` + `engine/rules.py`*
*AI review: `engine/agent_orchestrator.py` + `engine/agents/`*
*Plan mutation: `engine/plan_mutator.py`*

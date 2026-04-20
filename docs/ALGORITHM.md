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

*Algorithm implemented in `engine/packager.py` | Rule evaluators in `engine/rules.py`*

"""Parse FMECA Excel workbook → normalised DB rows."""

import uuid
import pandas as pd
from db.models import FunctionalLocation, FailureMode, Task
from db.database import get_session

# Map lowercase-stripped column names to internal field names
_COL_MAP = {
    # Hierarchy
    "train": "train",
    "system code": "system_code",
    "system description": "system_desc",
    "floc": "floc",
    "floc description": "floc_desc",
    "asset class": "asset_class",
    "floc level": "floc_level",
    "parent floc": "parent_floc",
    # Failure mode
    "function": "function",
    "functional failure": "functional_failure",
    "failure mode": "failure_mode",
    "failure effect": "failure_effect",
    "criticality": "criticality",
    # Task
    "task type": "task_type",
    "task description": "description",
    "maintenance task": "description",
    "interval value": "interval",
    "interval": "interval",
    "interval unit": "interval_unit",
    "est. duration (hrs)": "duration_hours",
    "duration (hrs)": "duration_hours",
    "duration": "duration_hours",
    "planner group": "resource_type",
    "resource type": "resource_type",
    "trade": "resource_type",
    "work centre": "work_centre",
    "shutdown required": "is_shutdown",
    "online": "is_online",
    "is regulatory": "is_regulatory",
    "regulatory": "is_regulatory",
    "materials / parts": "materials",
    "materials": "materials",
}


def _normalise_cols(df: pd.DataFrame) -> pd.DataFrame:
    mapping = {}
    for col in df.columns:
        key = col.strip().lower()
        if key in _COL_MAP:
            mapping[col] = _COL_MAP[key]
    return df.rename(columns=mapping)


def _safe_bool(val) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        return val.strip().lower() in ("yes", "true", "1", "y", "x")
    return False


def _safe_float(val, default=1.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=1) -> int:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _str(val) -> str:
    if val is None or (isinstance(val, float) and val != val):  # NaN check
        return ""
    return str(val).strip()


def load_fmeca(filepath: str, dataset_id=None) -> dict:
    """Parse FMECA Excel file and persist to DB. Returns summary dict."""
    if dataset_id is None:
        dataset_id = str(uuid.uuid4())

    df = pd.read_excel(filepath, engine="openpyxl")
    df = _normalise_cols(df)
    df = df.dropna(how="all")

    session = get_session()
    warnings = []

    # FLOC hierarchy cache: key → FunctionalLocation ORM object
    floc_cache: dict[tuple, FunctionalLocation] = {}

    def _get_or_create_hierarchy(train, system_code, system_desc, floc_code, floc_desc, asset_class):
        """Build 3-level hierarchy: Train → System → FLOC."""

        # Level 1: Train
        k1 = (_str(train),)
        if k1 not in floc_cache:
            f = FunctionalLocation(
                name=k1[0] or "UNKNOWN",
                level=1,
                asset_class=None,
                is_safety_critical=False,
                dataset_id=dataset_id,
            )
            session.add(f)
            session.flush()
            floc_cache[k1] = f

        # Level 2: System (use code as key, description as name)
        sys_name = _str(system_desc) or _str(system_code) or "UNKNOWN"
        k2 = (k1[0], _str(system_code))
        if k2 not in floc_cache:
            f = FunctionalLocation(
                parent_id=floc_cache[k1].id,
                name=sys_name,
                level=2,
                asset_class=None,
                is_safety_critical=False,
                dataset_id=dataset_id,
            )
            session.add(f)
            session.flush()
            floc_cache[k2] = f

        # Level 3: FLOC (equipment / sub-system)
        floc_name = _str(floc_desc) or _str(floc_code) or "UNKNOWN"
        k3 = (k1[0], _str(system_code), _str(floc_code))
        if k3 not in floc_cache:
            f = FunctionalLocation(
                parent_id=floc_cache[k2].id,
                name=floc_name,
                level=3,
                asset_class=_str(asset_class) or None,
                is_safety_critical=False,
                dataset_id=dataset_id,
            )
            session.add(f)
            session.flush()
            floc_cache[k3] = f

        return floc_cache[k3]

    task_count = 0

    for idx, row in df.iterrows():
        try:
            # Determine online/offline
            is_online = True
            if "is_online" in row.index and pd.notna(row.get("is_online")):
                is_online = _safe_bool(row.get("is_online"))
            elif "is_shutdown" in row.index and pd.notna(row.get("is_shutdown")):
                is_online = not _safe_bool(row.get("is_shutdown"))

            leaf_floc = _get_or_create_hierarchy(
                train=row.get("train", ""),
                system_code=row.get("system_code", ""),
                system_desc=row.get("system_desc", ""),
                floc_code=row.get("floc", ""),
                floc_desc=row.get("floc_desc", ""),
                asset_class=row.get("asset_class", ""),
            )

            fm = FailureMode(
                functional_location_id=leaf_floc.id,
                function=_str(row.get("function", "")),
                functional_failure=_str(row.get("functional_failure", "")),
                failure_mode=_str(row.get("failure_mode", "")),
                failure_effect=_str(row.get("failure_effect", "")),
                criticality=_str(row.get("criticality", "")),
            )
            session.add(fm)
            session.flush()

            # Resource type: prefer Planner Group, fall back to Work Centre
            resource = _str(row.get("resource_type", "")).upper()
            if not resource:
                resource = _str(row.get("work_centre", "MECH")).upper()
            if not resource:
                resource = "MECH"

            task = Task(
                failure_mode_id=fm.id,
                task_type=_str(row.get("task_type", "")),
                description=_str(row.get("description", "")),
                interval=_safe_int(row.get("interval", 1)),
                interval_unit=_str(row.get("interval_unit", "months")) or "months",
                duration_hours=_safe_float(row.get("duration_hours", 1.0)),
                resource_type=resource,
                is_online=is_online,
                is_regulatory=_safe_bool(row.get("is_regulatory", False)),
                materials=_str(row.get("materials", "")),
                dataset_id=dataset_id,
            )
            session.add(task)
            task_count += 1

        except Exception as e:
            warnings.append(f"Row {idx}: {e}")

    session.commit()
    session.close()

    return {
        "dataset_id": dataset_id,
        "floc_count": len(floc_cache),
        "task_count": task_count,
        "warnings": warnings,
    }


def get_dataset_stats(dataset_id: str) -> dict:
    """Return summary statistics for a loaded dataset."""
    session = get_session()
    try:
        tasks = session.query(Task).filter(Task.dataset_id == dataset_id).all()
        flocs = session.query(FunctionalLocation).filter(
            FunctionalLocation.dataset_id == dataset_id
        ).all()

        trains = {f.name for f in flocs if f.level == 1}
        systems = {f.name for f in flocs if f.level == 2}
        asset_classes = {f.asset_class for f in flocs if f.level == 3 and f.asset_class}

        task_types: dict = {}
        resource_types: dict = {}
        criticalities: dict = {}

        for t in tasks:
            task_types[t.task_type] = task_types.get(t.task_type, 0) + 1
            resource_types[t.resource_type] = resource_types.get(t.resource_type, 0) + 1

        for task in tasks:
            fm = session.get(FailureMode, task.failure_mode_id)
            if fm:
                criticalities[fm.criticality] = criticalities.get(fm.criticality, 0) + 1

        return {
            "total_tasks": len(tasks),
            "total_flocs": len(flocs),
            "trains": len(trains),
            "systems": len(systems),
            "asset_classes": len(asset_classes),
            "task_types": task_types,
            "resource_types": resource_types,
            "criticalities": criticalities,
        }
    finally:
        session.close()

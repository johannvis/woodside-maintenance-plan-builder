import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///woodside_maintenance.db")

DEFAULT_DATASET_PATH = "Data/LNG_Train_FLOC_FMECA_Synthetic_plus.xlsx"
DEFAULT_RULES_PATH = "db/seed/default_rules.json"

APP_TITLE = "Woodside Maintenance Plan Builder"
APP_ICON = "⚙️"

# Packaging defaults
DEFAULT_MAX_DURATION_HOURS = 8
DEFAULT_GROUPING_LEVEL = 3
DEFAULT_PLAN_PREFIX = "PM-LNG"
DEFAULT_ITEM_PREFIX = "ITEM"

# SAP reference defaults
DEFAULT_PLANT = "WA01"

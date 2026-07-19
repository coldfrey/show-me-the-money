"""Shared configuration constants."""

from datetime import date

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1"
WASTEDWIND_BASE = "https://wastedwind.energy"
EARLIEST_DATE = date(2026, 1, 1)
MIN_ATTEMPT_INTERVAL_S = 0.25
MAX_RETRIES = 3

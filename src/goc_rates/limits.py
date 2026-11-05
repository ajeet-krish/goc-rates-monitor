"""Central numeric and size bounds for the GoC rates pipeline.

All bounds are inclusive caps that fail closed. Product tenors cover the
30 year GoC benchmark set, while the wider tenor cap allows curve
evaluation headroom. Counts bound upstream payloads and local recompute
loops so a compromised source cannot exhaust memory.
"""

from __future__ import annotations

MAX_PRODUCT_TENOR_YEARS: float = 30.0
MAX_TENOR_YEARS: float = 60.0
MAX_PERIODS: int = 120
MAX_KNOTS: int = 10
MIN_BACKTEST: int = 254
MAX_BACKTEST_OBS: int = 2000
MAX_SPREAD_RECORDS: int = 2000
MAX_HISTORY_OBS: int = 2750
MAX_QUANTITIES: int = 10000
MAX_BILL_DAYS: int = 366
MAX_CARRY_HORIZON: float = 1.0
MIN_YIELD: float = -20.0
MAX_YIELD: float = 30.0
MAX_ABS_SLOPE_BP: float = 5000.0
MAX_SOURCE_ID_LENGTH: int = 80
MAX_CPI_COMPONENTS: int = 128
MAX_CPI_MONTHS: int = 240
MAX_BULK_BYTES: int = 256 * 1024 * 1024
MAX_BULK_MEMBER_BYTES: int = 256 * 1024 * 1024
MAX_BULK_MEMBERS: int = 64
MAX_SWITCH_EVENTS: int = 64
MAX_DOD_RECORDS: int = 4
MAX_SWITCH_FEED_BYTES: int = 64 * 1024
MAX_CASHFLOWS_PER_INSTRUMENT: int = 130
MAX_BOOTSTRAP_ANCHORS: int = 260
BOOTSTRAP_PRICE_TOLERANCE_BP: float = 1.0
MAX_BACKFILL_DAILY_ROWS: int = 2750
MIN_BACKFILL_DAILY_ROWS: int = 250
MAX_BACKFILL_CPI_MONTHS: int = 60
MAX_BACKFILL_BYTES: int = 5 * 1024 * 1024

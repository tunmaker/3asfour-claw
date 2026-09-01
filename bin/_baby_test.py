#!/usr/bin/env python3
"""python3 bin/_baby_test.py -- runs against a throwaway data dir."""
import datetime as dt
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _baby  # noqa: E402

FAILS = []


def check(name, cond):
    print(f"{'ok  ' if cond else 'FAIL'} {name}")
    if not cond:
        FAILS.append(name)


tmp = tempfile.mkdtemp()
cfg = _baby.settings({"ABBES_DATA_DIR": tmp, "DEDUPE_WINDOW_SECS": "90", "BABY_FEED_ML": "90"})
tz = cfg["tz"]

# A fixed clock so times are checkable.
fixed = dt.datetime(2026, 9, 1, 14, 30, tzinfo=tz)
_baby.now = lambda c: fixed

check("empty journal has a polite summary", "لا توجد" in _baby.summary(cfg))

stored, assumed = _baby.feed(cfg)
check("feed with nothing said uses the configured default", '"ml": 90' in stored)
check("and says it assumed", any("الافتراضية" in a for a in assumed))
check("stored line is on disk verbatim", stored in cfg["journal"].read_text())

try:
    _baby.feed(cfg)
    check("an identical feed within the window is refused", False)
except _baby.JournalError as e:
    check("an identical feed within the window is refused", "ALREADY" in str(e))

stored, assumed = _baby.feed(cfg, 150, "bottle")
check("explicit amount stored", '"ml": 150' in stored and not assumed)
stored, assumed = _baby.feed(cfg, None, "again")
check("next feed with no amount copies the last one", '"ml": 150' in stored)
check("and says so", any("السابقة" in a for a in assumed))

stored, assumed = _baby.sleep(cfg)
check("sleep with no times starts now, open", '"end"' not in stored and any("الآن" in a for a in assumed))
try:
    _baby.sleep(cfg)
    check("a second open sleep is refused", False)
except _baby.JournalError:
    check("a second open sleep is refused", True)
stored, assumed, minutes = _baby.wake(cfg, "15:10")
check("wake closes it and computes the length", minutes == 40)
check("last() reports the closed sleep", "من 14:30 إلى 15:10" in _baby.last(cfg))

stored, assumed = _baby.sleep(cfg, "22:30", "06:00", "night")
check("a sleep across midnight is 450 minutes", '"minutes": 450' in stored)
check("an end before start yesterday is not in the future", '"ts": "2026-08-31T22:30' in stored)

stored, assumed = _baby.diaper(cfg)
check("diaper defaults to wet and says so", '"state": "wet"' in stored and assumed)
try:
    _baby.diaper(cfg, "purple")
    check("an unknown diaper state is refused", False)
except _baby.JournalError:
    check("an unknown diaper state is refused", True)

s = _baby.summary(cfg)
check("today's summary counts feeds and ml", "الرضعات: 3" in s and "390 مل" in s)
check("today's summary shows sleep", "النوم:" in s)
check("list shows Arabic kinds", "رضعة" in _baby.listing(cfg, 2) and "حفاض" in _baby.listing(cfg, 2))

try:
    _baby.wake(cfg)
    check("wake with no open sleep is refused", False)
except _baby.JournalError:
    check("wake with no open sleep is refused", True)

# Legacy import: two CSV streams become one journal, once.
tmp2 = tempfile.mkdtemp()
cfg2 = _baby.settings({"ABBES_DATA_DIR": tmp2})
legacy = cfg2["legacy_dir"]
legacy.mkdir(parents=True)
(legacy / "feed-2026-08.csv").write_text("timestamp,amount_ml,note\n2026-08-28 19:50,110,evening\n")
(legacy / "sleep-2026-08.csv").write_text("date,start,end,minutes,note\n2026-08-30,03:44,03:45,1,short\n")
n = _baby.import_legacy(cfg2)
check("legacy rows imported", n == 2)
check("legacy files renamed, not deleted", (legacy / "feed-2026-08.csv.imported").exists())
check("imported sleep is closed", '"minutes": 1' in cfg2["journal"].read_text())
check("import runs once", _baby.import_legacy(cfg2) == 0)

print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
sys.exit(1 if FAILS else 0)

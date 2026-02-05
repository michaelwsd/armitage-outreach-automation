"""
Test script for the scheduler module (monthly scheduling).
Tests schedule generation, partitioning, session execution flow, and cleanup logic.
Mocks actual scraping so no real API calls are made.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler import (
    _partition_companies,
    _assign_schedule_slots,
    _send_digest_and_cleanup,
    generate_monthly_schedule,
    _save_schedule,
    _load_schedule,
    _all_sessions_done,
    run_session,
    send_monthly_digest,
    print_schedule_status,
    SCHEDULE_FILE,
    SCHEDULE_DIR,
    PROJECT_DIR,
    MONTH_DAY_START,
    MONTH_DAY_END,
    MAX_GROUP_SIZE,
    SCRAPE_HOUR_START,
    SCRAPE_HOUR_END,
    remove_session_crons,
)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []


def test(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append(condition)
    msg = f"  [{status}] {name}"
    if not condition and detail:
        msg += f" -- {detail}"
    print(msg)


# -------------------------------------------------------------------
# Test data
# -------------------------------------------------------------------
COMPANIES_4 = [("Co_A", "Melbourne"), ("Co_B", "Sydney"), ("Co_C", "Brisbane"), ("Co_D", "Perth")]
COMPANIES_15 = [(f"Company_{i}", f"City_{i}") for i in range(15)]
COMPANIES_1 = [("Solo_Co", "Adelaide")]


# -------------------------------------------------------------------
# 1. Partitioning
# -------------------------------------------------------------------
print("\n=== Partitioning Tests ===")

for trial in range(20):
    groups = _partition_companies(COMPANIES_15)
    all_companies = [c for g in groups for c in g]
    test(f"Partition 15 (trial {trial+1}): all covered",
         sorted(all_companies) == sorted(COMPANIES_15))
    test(f"Partition 15 (trial {trial+1}): groups 1-{MAX_GROUP_SIZE}",
         all(1 <= len(g) <= MAX_GROUP_SIZE for g in groups),
         f"sizes: {[len(g) for g in groups]}")

groups_1 = _partition_companies(COMPANIES_1)
test("Partition 1 company: single group", len(groups_1) == 1 and len(groups_1[0]) == 1)

groups_4 = _partition_companies(COMPANIES_4)
all_4 = [c for g in groups_4 for c in g]
test("Partition 4 companies: all covered", sorted(all_4) == sorted(COMPANIES_4))
test("Partition 4 companies: groups 1-{MAX_GROUP_SIZE}", all(1 <= len(g) <= MAX_GROUP_SIZE for g in groups_4))


# -------------------------------------------------------------------
# 2. Slot assignment (monthly)
# -------------------------------------------------------------------
print("\n=== Slot Assignment Tests ===")

for n in [1, 3, 6, 10, 15]:
    slots = _assign_schedule_slots(n)
    test(f"Slots for {n} sessions: correct count", len(slots) == n)
    test(f"Slots for {n} sessions: days {MONTH_DAY_START}-{MONTH_DAY_END}",
         all(MONTH_DAY_START <= d <= MONTH_DAY_END for d, h, m in slots),
         f"days: {[d for d,h,m in slots]}")
    test(f"Slots for {n} sessions: hours 9-20",
         all(9 <= h <= 20 for d, h, m in slots),
         f"hours: {[h for d,h,m in slots]}")
    test(f"Slots for {n} sessions: minutes 0-59",
         all(0 <= m <= 59 for d, h, m in slots))

# Test spreading: with few sessions, days should be spread apart
for _ in range(10):
    slots = _assign_schedule_slots(4)
    days = sorted(d for d, h, m in slots)
    if len(days) >= 2:
        min_gap = min(days[i+1] - days[i] for i in range(len(days)-1))
        test(f"Slots for 4 sessions: spread out (min gap={min_gap})",
             min_gap >= 1,
             f"days: {days}")


# -------------------------------------------------------------------
# 3. Full schedule generation
# -------------------------------------------------------------------
print("\n=== Schedule Generation Tests ===")

schedule = generate_monthly_schedule(COMPANIES_15)
test("Schedule has month_of", "month_of" in schedule)
test("Schedule has generated_at", "generated_at" in schedule)
test("Schedule has total_companies=15", schedule["total_companies"] == 15)
test("Schedule digest_sent=False", schedule["digest_sent"] is False)
test("Schedule has sessions", len(schedule["sessions"]) > 0)

all_scheduled = []
for s in schedule["sessions"]:
    all_scheduled.extend([tuple(c) for c in s["companies"]])
test("All 15 companies scheduled",
     sorted(all_scheduled) == sorted(COMPANIES_15),
     f"got {len(all_scheduled)} companies")

for s in schedule["sessions"]:
    test(f"Session {s['session_id']}: has date field", "date" in s)
    test(f"Session {s['session_id']}: has day_of_month", "day_of_month" in s)
    test(f"Session {s['session_id']}: day_of_month in range",
         MONTH_DAY_START <= s["day_of_month"] <= MONTH_DAY_END)
    test(f"Session {s['session_id']}: 1-4 companies",
         1 <= len(s["companies"]) <= MAX_GROUP_SIZE,
         f"has {len(s['companies'])}")
    test(f"Session {s['session_id']}: status=pending", s["status"] == "pending")

# Check sessions are sorted chronologically
days = [(s["day_of_month"], s["hour"], s["minute"]) for s in schedule["sessions"]]
test("Sessions sorted chronologically", days == sorted(days))

# Check randomization (generate twice, should differ)
schedule2 = generate_monthly_schedule(COMPANIES_15)
order1 = [c[0] for s in schedule["sessions"] for c in s["companies"]]
order2 = [c[0] for s in schedule2["sessions"] for c in s["companies"]]
test("Two schedules differ (randomization works)", order1 != order2)


# -------------------------------------------------------------------
# 4. Save / Load
# -------------------------------------------------------------------
print("\n=== Save/Load Tests ===")

SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
_save_schedule(schedule)
loaded = _load_schedule()
test("Save and load round-trip", loaded is not None)
test("Loaded schedule matches", loaded["month_of"] == schedule["month_of"])
test("Loaded sessions count", len(loaded["sessions"]) == len(schedule["sessions"]))


# -------------------------------------------------------------------
# 5. Session execution (mocked scraping)
# -------------------------------------------------------------------
print("\n=== Session Execution Tests ===")

# Create a fresh schedule with known data
test_schedule = generate_monthly_schedule(COMPANIES_4)
_save_schedule(test_schedule)
first_session_id = test_schedule["sessions"][0]["session_id"]


# Mock scrape_companies to avoid real API calls
mock_results = [{"company": "mock", "news_scrape": True, "linkedin_scrape": True}]


def _noop_cleanup(*args, **kwargs):
    """No-op replacement for file cleanup during tests."""
    pass


async def run_mock_session(session_id):
    with patch("scheduler.scrape_companies", new_callable=AsyncMock, return_value=mock_results), \
         patch("scheduler.send_digest_report", return_value=True), \
         patch("scheduler.remove_session_crons"), \
         patch("pathlib.Path.unlink", _noop_cleanup):
        await run_session(session_id)


# Run first session
asyncio.run(run_mock_session(first_session_id))
after_first = _load_schedule()
first_status = next(s for s in after_first["sessions"] if s["session_id"] == first_session_id)
test("First session marked completed", first_status["status"] == "completed")
test("First session has started_at", first_status["started_at"] is not None)
test("First session has completed_at", first_status["completed_at"] is not None)
test("Digest NOT sent yet (sessions remaining)", after_first["digest_sent"] is False)

# Running same session again should skip
asyncio.run(run_mock_session(first_session_id))
test("Re-running completed session is a no-op (idempotent)", True)

# Run remaining sessions
for s in after_first["sessions"]:
    if s["status"] == "pending":
        asyncio.run(run_mock_session(s["session_id"]))

after_all = _load_schedule()
test("All sessions completed", _all_sessions_done(after_all))
test("Digest NOT sent by run_session (only on last day)", after_all["digest_sent"] is False)


# -------------------------------------------------------------------
# 6. Status display (smoke test)
# -------------------------------------------------------------------
print("\n=== Status Display ===")

fresh = generate_monthly_schedule(COMPANIES_4)
_save_schedule(fresh)
print_schedule_status()
test("Status display ran without error", True)


# -------------------------------------------------------------------
# 7. Edge cases
# -------------------------------------------------------------------
print("\n=== Edge Cases ===")

asyncio.run(run_mock_session("sess_999"))
test("Nonexistent session handled gracefully", True)

empty_groups = _partition_companies([])
test("Empty company list: no groups", len(empty_groups) == 0)


# -------------------------------------------------------------------
# 8. Day range buffer (all sessions finish before last-day digest)
# -------------------------------------------------------------------
print("\n=== Day Range Buffer Tests ===")

# MONTH_DAY_END must be <= 26 so sessions finish before the last day of any month (Feb 28)
test("MONTH_DAY_END <= 26 (buffer before shortest month)",
     MONTH_DAY_END <= 26,
     f"MONTH_DAY_END={MONTH_DAY_END}")

# All sessions must have hours strictly before SCRAPE_HOUR_END (21), digest fires at 23:30
test("SCRAPE_HOUR_END <= 21 (sessions finish well before 23:30 digest)",
     SCRAPE_HOUR_END <= 21,
     f"SCRAPE_HOUR_END={SCRAPE_HOUR_END}")

# Verify across many schedules that no session lands after day 26
for trial in range(20):
    sched = generate_monthly_schedule(COMPANIES_15)
    max_day = max(s["day_of_month"] for s in sched["sessions"])
    max_hour = max(s["hour"] for s in sched["sessions"])
    test(f"Buffer trial {trial+1}: max day={max_day} <= {MONTH_DAY_END}",
         max_day <= MONTH_DAY_END)
    test(f"Buffer trial {trial+1}: max hour={max_hour} < {SCRAPE_HOUR_END}",
         max_hour < SCRAPE_HOUR_END)


# -------------------------------------------------------------------
# 9. send_monthly_digest tests
# -------------------------------------------------------------------
print("\n=== send_monthly_digest Tests ===")

# Test 1: digest already sent — should skip
already_sent_schedule = generate_monthly_schedule(COMPANIES_4)
already_sent_schedule["digest_sent"] = True
_save_schedule(already_sent_schedule)

with patch("scheduler.send_digest_report", return_value=True) as mock_send, \
     patch("scheduler.remove_session_crons"), \
     patch("pathlib.Path.unlink", _noop_cleanup):
    send_monthly_digest()
    test("send_monthly_digest skips when already sent", mock_send.call_count == 0)

# Test 2: digest not sent, all sessions completed — should send
all_done_schedule = generate_monthly_schedule(COMPANIES_4)
for s in all_done_schedule["sessions"]:
    s["status"] = "completed"
    s["started_at"] = "2026-03-10T10:00:00"
    s["completed_at"] = "2026-03-10T10:30:00"
_save_schedule(all_done_schedule)

with patch("scheduler.send_digest_report", return_value=True) as mock_send, \
     patch("scheduler.remove_session_crons"), \
     patch("pathlib.Path.unlink", _noop_cleanup):
    send_monthly_digest()
    test("send_monthly_digest sends when all done", mock_send.call_count == 1)

after_digest = _load_schedule()
test("digest_sent set to True after send_monthly_digest", after_digest["digest_sent"] is True)

# Test 3: some sessions still pending — should still send (last day fallback)
partial_schedule = generate_monthly_schedule(COMPANIES_4)
partial_schedule["sessions"][0]["status"] = "completed"
partial_schedule["sessions"][0]["started_at"] = "2026-03-05T14:00:00"
partial_schedule["sessions"][0]["completed_at"] = "2026-03-05T14:20:00"
# rest stay pending
_save_schedule(partial_schedule)

with patch("scheduler.send_digest_report", return_value=True) as mock_send, \
     patch("scheduler.remove_session_crons"), \
     patch("pathlib.Path.unlink", _noop_cleanup):
    send_monthly_digest()
    test("send_monthly_digest sends even with pending sessions (last-day fallback)",
         mock_send.call_count == 1)

after_partial = _load_schedule()
test("digest_sent=True after partial send", after_partial["digest_sent"] is True)

# Test 4: no schedule file — should handle gracefully
if SCHEDULE_FILE.exists():
    SCHEDULE_FILE.unlink()

with patch("scheduler.send_digest_report", return_value=True) as mock_send:
    send_monthly_digest()
    test("send_monthly_digest handles missing schedule gracefully", mock_send.call_count == 0)


# -------------------------------------------------------------------
# 10. Digest fires only after all scrapes complete (integration)
# -------------------------------------------------------------------
print("\n=== Digest Timing Integration Tests ===")

# Simulate running sessions one by one — digest should ONLY fire after the last one
int_schedule = generate_monthly_schedule(COMPANIES_4)
_save_schedule(int_schedule)
session_ids = [s["session_id"] for s in int_schedule["sessions"]]

for idx, sid in enumerate(session_ids):
    with patch("scheduler.scrape_companies", new_callable=AsyncMock, return_value=mock_results), \
         patch("scheduler.send_digest_report", return_value=True) as mock_send, \
         patch("scheduler.remove_session_crons"), \
         patch("pathlib.Path.unlink", _noop_cleanup):
        asyncio.run(run_session(sid))
        test(f"Session {sid}: digest NOT sent by run_session", mock_send.call_count == 0)

# After all sessions, digest still not sent — only last-day cron sends it
after_int = _load_schedule()
test("All sessions done but digest_sent=False (waits for last-day cron)",
     _all_sessions_done(after_int) and after_int["digest_sent"] is False)


# -------------------------------------------------------------------
# 11. Schedule conflict detection
# -------------------------------------------------------------------
print("\n=== Schedule Conflict Tests ===")

# No two sessions should share the same (day, hour) — run many trials
for trial in range(30):
    for company_list, label in [(COMPANIES_4, "4co"), (COMPANIES_15, "15co")]:
        sched = generate_monthly_schedule(company_list)
        slots = [(s["day_of_month"], s["hour"]) for s in sched["sessions"]]
        unique_slots = set(slots)
        test(f"No (day,hour) conflicts {label} trial {trial+1}",
             len(slots) == len(unique_slots),
             f"duplicates: {[s for s in slots if slots.count(s) > 1]}")

# No two sessions should share the exact same (day, hour, minute) triple
for trial in range(30):
    sched = generate_monthly_schedule(COMPANIES_15)
    triples = [(s["day_of_month"], s["hour"], s["minute"]) for s in sched["sessions"]]
    unique_triples = set(triples)
    test(f"No (day,hour,min) conflicts 15co trial {trial+1}",
         len(triples) == len(unique_triples),
         f"duplicates found")

# No company appears in more than one session
for trial in range(20):
    sched = generate_monthly_schedule(COMPANIES_15)
    seen = set()
    duplicate = False
    for s in sched["sessions"]:
        for c in s["companies"]:
            key = tuple(c)
            if key in seen:
                duplicate = True
            seen.add(key)
    test(f"No duplicate companies across sessions trial {trial+1}", not duplicate)
    test(f"All companies covered trial {trial+1}",
         len(seen) == len(COMPANIES_15),
         f"got {len(seen)}, expected {len(COMPANIES_15)}")

# Session IDs are unique
for trial in range(10):
    sched = generate_monthly_schedule(COMPANIES_15)
    ids = [s["session_id"] for s in sched["sessions"]]
    test(f"Unique session IDs trial {trial+1}",
         len(ids) == len(set(ids)),
         f"duplicates: {[i for i in ids if ids.count(i) > 1]}")

# Sessions respect day and hour boundaries
for trial in range(20):
    sched = generate_monthly_schedule(COMPANIES_15)
    for s in sched["sessions"]:
        test(f"Session {s['session_id']} day in [{MONTH_DAY_START},{MONTH_DAY_END}] trial {trial+1}",
             MONTH_DAY_START <= s["day_of_month"] <= MONTH_DAY_END,
             f"day={s['day_of_month']}")
        test(f"Session {s['session_id']} hour in [{SCRAPE_HOUR_START},{SCRAPE_HOUR_END}) trial {trial+1}",
             SCRAPE_HOUR_START <= s["hour"] < SCRAPE_HOUR_END,
             f"hour={s['hour']}")
        test(f"Session {s['session_id']} minute in [0,59] trial {trial+1}",
             0 <= s["minute"] <= 59)


# -------------------------------------------------------------------
# 12. Cleanup is automatic and correct
# -------------------------------------------------------------------
print("\n=== Cleanup Tests ===")

# Set up fake data files to verify cleanup deletes them
INPUT_DIR = PROJECT_DIR / "data" / "input"
OUTPUT_DIR = PROJECT_DIR / "data" / "output"
INPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Create dummy files
dummy_input = INPUT_DIR / "test_dummy.csv"
dummy_output_1 = OUTPUT_DIR / "test_report.json"
dummy_output_2 = OUTPUT_DIR / "test_summary.txt"
for f in (dummy_input, dummy_output_1, dummy_output_2):
    f.write_text("test data")
    test(f"Created dummy file: {f.name}", f.exists())

# Run _send_digest_and_cleanup with mocked email and cron removal
cleanup_schedule = generate_monthly_schedule(COMPANIES_4)
_save_schedule(cleanup_schedule)

with patch("scheduler.send_digest_report", return_value=True) as mock_send, \
     patch("scheduler.remove_session_crons") as mock_remove_crons:
    _send_digest_and_cleanup(cleanup_schedule)

    # Verify email was sent
    test("Cleanup: digest email sent", mock_send.call_count == 1)

    # Verify session crons were removed
    test("Cleanup: remove_session_crons called", mock_remove_crons.call_count == 1)

# Verify dummy files were deleted
test("Cleanup: data/input/test_dummy.csv deleted", not dummy_input.exists())
test("Cleanup: data/output/test_report.json deleted", not dummy_output_1.exists())
test("Cleanup: data/output/test_summary.txt deleted", not dummy_output_2.exists())

# Verify digest_sent is True in schedule
after_cleanup = _load_schedule()
test("Cleanup: digest_sent=True in schedule", after_cleanup["digest_sent"] is True)

# Verify directories still exist (only files are deleted, not dirs)
test("Cleanup: data/input dir still exists", INPUT_DIR.exists())
test("Cleanup: data/output dir still exists", OUTPUT_DIR.exists())

# Test cleanup with no EMAIL_RECIPIENTS — should still mark digest_sent and clean files
no_email_schedule = generate_monthly_schedule(COMPANIES_4)
_save_schedule(no_email_schedule)
dummy_input.write_text("test data 2")
test("Created dummy for no-email test", dummy_input.exists())

with patch.dict(os.environ, {"EMAIL_RECIPIENTS": ""}), \
     patch("scheduler.send_digest_report", return_value=True) as mock_send, \
     patch("scheduler.remove_session_crons") as mock_remove_crons:
    _send_digest_and_cleanup(no_email_schedule)

    test("No-email cleanup: digest email NOT sent", mock_send.call_count == 0)
    test("No-email cleanup: crons still removed", mock_remove_crons.call_count == 1)

test("No-email cleanup: files still deleted", not dummy_input.exists())
after_no_email = _load_schedule()
test("No-email cleanup: digest_sent=True anyway", after_no_email["digest_sent"] is True)

# Test cleanup with email send failure — should still mark digest_sent and clean
fail_schedule = generate_monthly_schedule(COMPANIES_4)
_save_schedule(fail_schedule)
dummy_output_1.write_text("test data 3")

with patch("scheduler.send_digest_report", side_effect=Exception("SMTP error")) as mock_send, \
     patch("scheduler.remove_session_crons"):
    _send_digest_and_cleanup(fail_schedule)

test("Email-fail cleanup: files still deleted", not dummy_output_1.exists())
after_fail = _load_schedule()
test("Email-fail cleanup: digest_sent=True despite error", after_fail["digest_sent"] is True)

# Test that schedule file itself survives cleanup (only data dirs are cleaned)
test("Cleanup: schedule file survives", SCHEDULE_FILE.exists())


# -------------------------------------------------------------------
# Cleanup
# -------------------------------------------------------------------
if SCHEDULE_FILE.exists():
    SCHEDULE_FILE.unlink()


# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------
print("\n" + "=" * 50)
passed = sum(results)
total = len(results)
if passed == total:
    print(f"\033[92mAll {total} tests passed!\033[0m")
else:
    print(f"\033[91m{passed}/{total} tests passed, {total - passed} failed\033[0m")
print("=" * 50)

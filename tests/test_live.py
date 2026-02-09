"""
Live test: schedules real scraping sessions within the next 10 minutes.
Installs actual cron entries so you can verify the full pipeline end-to-end.

Usage:
    python test_live.py          # Generate schedule + install crons
    python test_live.py status   # Check progress
    python test_live.py cleanup  # Remove test crons and schedule

Watch the log:
    tail -f cron.log
"""
import sys
import random
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schedule.scheduler import (
    _partition_companies,
    _save_schedule,
    install_session_crons,
    remove_session_crons,
    print_schedule_status,
    SCHEDULE_DIR,
)
from scraper import read_companies_from_csv


def generate_live_schedule():
    """Generate a schedule with sessions spread across the next 10 minutes."""
    companies = read_companies_from_csv()
    if not companies:
        print("No companies found in data/input/companies.csv")
        return

    groups = _partition_companies(companies)
    now = datetime.now()

    # Space sessions 3 minutes apart, starting 2 minutes from now
    sessions = []
    for idx, group in enumerate(groups):
        run_at = now + timedelta(minutes=2 + idx * 3)

        sessions.append({
            "session_id": f"sess_{idx:03d}",
            "day_of_month": run_at.day,
            "day_name": run_at.strftime("%A"),
            "date": run_at.strftime("%Y-%m-%d"),
            "hour": run_at.hour,
            "minute": run_at.minute,
            "companies": [list(c) for c in group],
            "status": "pending",
            "started_at": None,
            "completed_at": None,
        })

    schedule = {
        "month_of": now.strftime("%Y-%m"),
        "generated_at": now.isoformat(timespec="seconds"),
        "total_companies": len(companies),
        "digest_sent": False,
        "sessions": sessions,
    }

    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    _save_schedule(schedule)
    install_session_crons(schedule)

    print(f"\nLive test schedule created at {now.strftime('%H:%M:%S')}")
    print(f"Companies: {len(companies)}, Sessions: {len(sessions)}")
    print(f"\nScheduled sessions:")
    for s in sessions:
        names = ", ".join(c[0] for c in s["companies"])
        print(f"  {s['date']} {s['hour']:02d}:{s['minute']:02d}  "
              f"({len(s['companies'])} companies: {names})")
    print(f"\nMonitor with:  tail -f cron.log")
    print(f"Check status:  python test_live.py status")
    print(f"Cleanup:       python test_live.py cleanup")


def cleanup():
    remove_session_crons()
    print("Test session crons removed.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print_schedule_status()
    elif len(sys.argv) > 1 and sys.argv[1] == "cleanup":
        cleanup()
    else:
        generate_live_schedule()

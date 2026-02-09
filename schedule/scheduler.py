import os
import sys
import json
import fcntl
import asyncio
import random
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

from scraper import read_companies_from_csv, scrape_companies
from utils.email_client import send_digest_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Paths & constants
# -------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent.parent
SCHEDULE_DIR = PROJECT_DIR / "data" / "schedule"
SCHEDULE_FILE = SCHEDULE_DIR / "monthly_schedule.json"
PYTHON_PATH = PROJECT_DIR / ".venv" / "bin" / "python"
CRON_LOG = PROJECT_DIR / "cron.log"

CRON_SESSION_TAG = "# ARMITAGE_SESSION"
CRON_META_TAG = "# ARMITAGE_META"

MIN_GROUP_SIZE = 1
MAX_GROUP_SIZE = 2
SCRAPE_HOUR_START = 9   # earliest session hour (inclusive)
SCRAPE_HOUR_END = 21    # latest session hour (exclusive)
INTER_COMPANY_DELAY_MIN = 300   # 5 minutes
INTER_COMPANY_DELAY_MAX = 900   # 15 minutes

MONTH_DAY_START = 2   # earliest day-of-month for sessions (skip 1st: meta-cron day)
MONTH_DAY_END = 26    # latest day-of-month (buffer before last-day digest cron)


# -------------------------------------------------------------------
# Schedule file I/O (with file locking)
# -------------------------------------------------------------------

def _load_schedule():
    if not SCHEDULE_FILE.exists():
        return None
    with open(SCHEDULE_FILE, "r") as f:
        return json.load(f)


def _save_schedule(schedule):
    SCHEDULE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULE_FILE, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(schedule, f, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)


# -------------------------------------------------------------------
# Schedule generation
# -------------------------------------------------------------------

def _partition_companies(companies):
    """Shuffle and split companies into random groups of 1-4."""
    shuffled = list(companies)
    random.shuffle(shuffled)

    groups = []
    i = 0
    while i < len(shuffled):
        remaining = len(shuffled) - i
        max_take = min(MAX_GROUP_SIZE, remaining)
        group_size = random.randint(MIN_GROUP_SIZE, max_take)
        groups.append(shuffled[i:i + group_size])
        i += group_size
    return groups


def _assign_schedule_slots(num_sessions):
    """Assign (day_of_month, hour, minute) to each session, spread across the month.

    Divides days 2-28 into equal segments and picks a random day within each
    segment so sessions are naturally spaced out.
    """
    available_range = MONTH_DAY_END - MONTH_DAY_START + 1  # 27 days

    if num_sessions <= available_range:
        # Divide the range into num_sessions segments, pick one day per segment
        segment_size = available_range / num_sessions
        day_assignments = []
        for i in range(num_sessions):
            seg_start = int(MONTH_DAY_START + i * segment_size)
            seg_end = int(MONTH_DAY_START + (i + 1) * segment_size) - 1
            seg_end = min(seg_end, MONTH_DAY_END)
            if seg_start > seg_end:
                seg_start = seg_end
            day_assignments.append(random.randint(seg_start, seg_end))
    else:
        # More sessions than available days — distribute evenly, multiple per day
        day_assignments = []
        base, remainder = divmod(num_sessions, available_range)
        for day in range(MONTH_DAY_START, MONTH_DAY_END + 1):
            count = base + (1 if remainder > 0 else 0)
            if remainder > 0:
                remainder -= 1
            day_assignments.extend([day] * count)
        random.shuffle(day_assignments)

    # Assign times, avoiding same (day, hour) collisions
    used_slots = set()
    slots = []
    for day in day_assignments:
        hour = None
        for _ in range(50):
            h = random.randint(SCRAPE_HOUR_START, SCRAPE_HOUR_END - 1)
            if (day, h) not in used_slots:
                hour = h
                used_slots.add((day, h))
                break
        if hour is None:
            hour = random.randint(SCRAPE_HOUR_START, SCRAPE_HOUR_END - 1)
        minute = random.randint(0, 59)
        slots.append((day, hour, minute))

    return slots


def generate_monthly_schedule(companies):
    """Generate a full monthly schedule covering all companies."""
    groups = _partition_companies(companies)
    slots = _assign_schedule_slots(len(groups))

    # Determine the target month (current month if early, next month if generated late)
    today = datetime.now()
    if today.day == 1:
        # Generated on the 1st — schedule for this month
        target_year, target_month = today.year, today.month
    else:
        # Generated mid-month — schedule for next month
        first_of_next = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        target_year, target_month = first_of_next.year, first_of_next.month

    sessions = []
    for idx, (group, (dom, hour, minute)) in enumerate(zip(groups, slots)):
        session_date = datetime(target_year, target_month, dom)
        sessions.append({
            "session_id": f"sess_{idx:03d}",
            "day_of_month": dom,
            "day_name": session_date.strftime("%A"),
            "date": session_date.strftime("%Y-%m-%d"),
            "hour": hour,
            "minute": minute,
            "companies": [list(c) for c in group],
            "status": "pending",
            "started_at": None,
            "completed_at": None,
        })

    sessions.sort(key=lambda s: (s["day_of_month"], s["hour"], s["minute"]))

    schedule = {
        "month_of": f"{target_year}-{target_month:02d}",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_companies": len(companies),
        "digest_sent": False,
        "sessions": sessions,
    }
    return schedule


# -------------------------------------------------------------------
# Crontab management
# -------------------------------------------------------------------

def _read_crontab():
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def _write_crontab(content):
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def install_session_crons(schedule):
    """Install one cron entry per session, removing old session crons first."""
    existing = _read_crontab()

    # Remove old session crons
    lines = [l for l in existing.splitlines() if CRON_SESSION_TAG not in l]

    # Add new session crons (using day-of-month, any day-of-week)
    for session in schedule["sessions"]:
        cron_line = (
            f"{session['minute']} {session['hour']} {session['day_of_month']} * * "
            f"cd {PROJECT_DIR} && {PYTHON_PATH} schedule/scheduler.py run-session {session['session_id']} "
            f">> {CRON_LOG} 2>&1 {CRON_SESSION_TAG}"
        )
        lines.append(cron_line)

    # Add last-day-of-month digest cron (fires on 28-31, only runs on actual last day)
    digest_line = (
        f'30 23 28-31 * * [ "$(date -d tomorrow +\\%d)" = "01" ] && '
        f"cd {PROJECT_DIR} && {PYTHON_PATH} schedule/scheduler.py send-digest "
        f">> {CRON_LOG} 2>&1 {CRON_SESSION_TAG}"
    )
    lines.append(digest_line)

    new_crontab = "\n".join(lines).strip() + "\n"
    _write_crontab(new_crontab)
    logger.info(f"Installed {len(schedule['sessions'])} session cron entries + last-day digest cron")


def install_meta_cron():
    """Install the monthly meta cron (1st of each month at 00:30) if not already present."""
    existing = _read_crontab()

    if CRON_META_TAG in existing:
        logger.info("Meta cron already installed")
        return

    meta_line = (
        f"30 0 1 * * cd {PROJECT_DIR} && {PYTHON_PATH} schedule/scheduler.py generate "
        f">> {CRON_LOG} 2>&1 {CRON_META_TAG}"
    )
    new_crontab = existing.rstrip("\n") + "\n" + meta_line + "\n" if existing.strip() else meta_line + "\n"
    _write_crontab(new_crontab)
    logger.info("Meta cron installed (1st of each month at 00:30)")


def remove_session_crons():
    """Remove all session cron entries."""
    existing = _read_crontab()
    lines = [l for l in existing.splitlines() if CRON_SESSION_TAG not in l]
    new_crontab = "\n".join(lines).strip() + "\n" if lines else ""
    _write_crontab(new_crontab)
    logger.info("Session crons removed")


def remove_all_armitage_crons():
    """Remove all armitage cron entries (session + meta)."""
    existing = _read_crontab()
    lines = [l for l in existing.splitlines()
             if CRON_SESSION_TAG not in l and CRON_META_TAG not in l]
    new_crontab = "\n".join(lines).strip() + "\n" if lines else ""
    _write_crontab(new_crontab)
    logger.info("All armitage crons removed")


def _remove_old_style_cron():
    """Remove the legacy untagged cron entry from cron_setup.py if present."""
    existing = _read_crontab()
    lines = [l for l in existing.splitlines()
             if not (l.strip() and "main.py" in l and "ARMITAGE" not in l)]
    new_crontab = "\n".join(lines).strip() + "\n" if lines else ""
    _write_crontab(new_crontab)


# -------------------------------------------------------------------
# Session execution
# -------------------------------------------------------------------

def _all_sessions_done(schedule):
    return all(s["status"] in ("completed", "failed") for s in schedule["sessions"])


async def run_session(session_id):
    """Execute a specific scraping session."""
    schedule = _load_schedule()
    if not schedule:
        logger.error("No schedule file found. Run 'python scheduler.py generate' first.")
        return

    session = None
    for s in schedule["sessions"]:
        if s["session_id"] == session_id:
            session = s
            break

    if not session:
        logger.error(f"Session {session_id} not found in schedule")
        return

    if session["status"] != "pending":
        logger.warning(f"Session {session_id} is already {session['status']}, skipping")
        return

    # Mark in-progress
    session["status"] = "in_progress"
    session["started_at"] = datetime.now().isoformat(timespec="seconds")
    _save_schedule(schedule)

    companies = [tuple(c) for c in session["companies"]]
    logger.info(f"Starting session {session_id}: {len(companies)} companies on {session['date']} ({session['day_name']})")

    try:
        results = await scrape_companies(companies, inter_delay=True)
        session["status"] = "completed"
    except Exception as e:
        logger.exception(f"Session {session_id} failed: {e}")
        session["status"] = "failed"

    session["completed_at"] = datetime.now().isoformat(timespec="seconds")
    _save_schedule(schedule)

    logger.info(f"Session {session_id} finished with status: {session['status']}")


def send_monthly_digest():
    """Send the digest on the last day of the month, regardless of session status."""
    schedule = _load_schedule()
    if not schedule:
        logger.info("No schedule found, nothing to send.")
        return

    if schedule.get("digest_sent", False):
        logger.info("Digest already sent this month, skipping.")
        return

    pending = [s for s in schedule["sessions"] if s["status"] == "pending"]
    if pending:
        logger.warning(f"{len(pending)} sessions never ran this month")

    logger.info("Last day of month: sending digest and cleaning up...")
    _send_digest_and_cleanup(schedule)


def _send_digest_and_cleanup(schedule):
    """Send the monthly digest email, clean up data, and remove session crons."""
    recipients_str = os.getenv("EMAIL_RECIPIENTS", "")
    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]

    if recipients:
        try:
            success = send_digest_report(recipients)
            if success:
                logger.info(f"Digest email sent to {recipients}")
            else:
                logger.warning("Digest email returned False")
        except Exception as e:
            logger.exception(f"Failed to send digest email: {e}")
    else:
        logger.warning("No EMAIL_RECIPIENTS configured, skipping digest email")

    schedule["digest_sent"] = True
    _save_schedule(schedule)

    # Clean up data/input and data/output so next month starts fresh
    for dirname in ("input", "output"):
        d = PROJECT_DIR / "data" / dirname
        if d.exists():
            for f in d.iterdir():
                if f.is_file():
                    f.unlink()
                    logger.info(f"Deleted {f}")
    logger.info("Data directories cleaned")

    # Uninstall all session crons — they're done for the month
    remove_session_crons()
    logger.info("Monthly cycle complete: digest sent, data cleaned, session crons removed")


# -------------------------------------------------------------------
# Monthly generation (meta-cron entrypoint)
# -------------------------------------------------------------------

def generate_and_install():
    """
    Generate a new monthly schedule and install session crons.
    Also handles sending the previous month's digest if it wasn't sent.
    """
    # Handle previous month's leftover digest (only if some sessions actually ran)
    old_schedule = _load_schedule()
    if old_schedule and not old_schedule.get("digest_sent", False):
        completed = [s for s in old_schedule["sessions"] if s["status"] in ("completed", "failed")]
        if completed:
            pending = [s for s in old_schedule["sessions"] if s["status"] == "pending"]
            if pending:
                logger.warning(f"{len(pending)} sessions from previous month never ran")
            logger.info("Sending previous month's digest as safety net...")
            _send_digest_and_cleanup(old_schedule)

    # Remove old-style cron from legacy cron_setup.py
    _remove_old_style_cron()

    # Generate new schedule
    companies = read_companies_from_csv()
    if not companies:
        logger.error("No companies found in CSV. Nothing to schedule.")
        return

    schedule = generate_monthly_schedule(companies)
    _save_schedule(schedule)
    install_session_crons(schedule)

    logger.info(f"New monthly schedule generated: {len(schedule['sessions'])} sessions "
                f"for {len(companies)} companies (month of {schedule['month_of']})")
    print_schedule_status()


# -------------------------------------------------------------------
# Status display
# -------------------------------------------------------------------

def print_schedule_status():
    schedule = _load_schedule()
    if not schedule:
        print("No schedule found. Run 'python scheduler.py generate' to create one.")
        return

    print(f"\nMonth of:    {schedule.get('month_of', schedule.get('week_of', 'unknown'))}")
    print(f"Generated:   {schedule['generated_at']}")
    print(f"Companies:   {schedule['total_companies']}")
    print(f"Digest sent: {schedule.get('digest_sent', False)}")
    print(f"\nSessions ({len(schedule['sessions'])}):")

    last_session = None
    for s in schedule["sessions"]:
        companies_str = ", ".join(c[0] for c in s["companies"])
        status_display = s["status"].center(12)
        date_str = s.get("date", "")
        print(f"  [{status_display}] {date_str} {s['day_name']:>9} {s['hour']:02d}:{s['minute']:02d}  "
              f"({len(s['companies'])} companies: {companies_str})")
        last_session = s

    if not schedule.get("digest_sent", False):
        print(f"\nDigest email: last day of month at 23:30")
    else:
        print(f"\nDigest email: already sent")
    print()


# -------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------

USAGE = """Usage:
    python schedule/scheduler.py generate            Generate schedule + install crons
    python schedule/scheduler.py run-session <id>    Run a specific session
    python schedule/scheduler.py send-digest         Send digest (last-day-of-month cron)
    python schedule/scheduler.py install-meta        Install the monthly meta cron
    python schedule/scheduler.py status              Print current schedule status
    python schedule/scheduler.py uninstall           Remove all armitage crons
"""

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    command = sys.argv[1]

    if command == "generate":
        generate_and_install()
    elif command == "run-session":
        if len(sys.argv) < 3:
            print("Error: session_id required")
            sys.exit(1)
        asyncio.run(run_session(sys.argv[2]))
    elif command == "send-digest":
        send_monthly_digest()
    elif command == "install-meta":
        install_meta_cron()
    elif command == "status":
        print_schedule_status()
    elif command == "uninstall":
        remove_all_armitage_crons()
        print("All armitage cron entries removed.")
    else:
        print(f"Unknown command: {command}")
        print(USAGE)
        sys.exit(1)

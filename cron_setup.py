import subprocess
from pathlib import Path


def generate_cron_job():
    """Generate and install a cron job that runs main.py every Sunday at noon."""
    project_dir = Path(__file__).resolve().parent
    python_path = project_dir / ".venv" / "bin" / "python"
    main_path = project_dir / "main.py"
    log_path = project_dir / "cron.log"

    cron_line = f"0 12 * * 0 cd {project_dir} && {python_path} {main_path} >> {log_path} 2>&1"

    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    if cron_line in existing:
        print("Cron job already installed.")
        return

    new_crontab = existing.rstrip("\n") + "\n" + cron_line + "\n" if existing.strip() else cron_line + "\n"
    subprocess.run(["crontab", "-"], input=new_crontab, text=True, check=True)
    print("Cron job installed successfully.")


if __name__ == "__main__":
    generate_cron_job()

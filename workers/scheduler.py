"""APScheduler entrypoint for local dev. In production prefer cron / GitHub Actions."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from scrapers.ingest import run_jumia_phones

logging.basicConfig(level=logging.INFO)


def main() -> None:
    sched = BlockingScheduler(timezone="Africa/Nairobi")
    # Every 6 hours
    sched.add_job(run_jumia_phones, "interval", hours=6, id="jumia-phones", next_run_time=None)
    logging.info("Scheduler started.")
    sched.start()


if __name__ == "__main__":
    main()

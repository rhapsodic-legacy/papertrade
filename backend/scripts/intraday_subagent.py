#!/usr/bin/env python3
"""Intraday conditional order subagent — runs via launchd every 5 minutes.

Checks pending conditional orders against live prices and executes when
triggers are met. Pure code logic, no LLM calls.

Uses a file lock to prevent overlapping runs. If the lock file exists and
the process that created it is still alive, this run exits immediately.

Usage:
    python3 scripts/intraday_subagent.py
"""

import asyncio
import fcntl
import os
import sys
import time

# Add backend to path so we can import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

LOCK_FILE = "/tmp/papertrade_intraday.lock"


def acquire_lock() -> int | None:
    """Try to acquire file lock. Returns fd on success, None if already locked."""
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Write our PID so it's inspectable
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, str(os.getpid()).encode())
        return fd
    except (OSError, IOError):
        return None


def release_lock(fd: int):
    """Release file lock."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        os.unlink(LOCK_FILE)
    except OSError:
        pass


async def main():
    from app.services.conditional_orders import check_and_execute_orders

    start = time.time()
    print(f"[INTRADAY] Starting conditional order check at {time.strftime('%H:%M:%S')}")

    try:
        result = check_and_execute_orders()
        # check_and_execute_orders is async
        if asyncio.iscoroutine(result):
            result = await result

        elapsed = time.time() - start
        print(
            f"[INTRADAY] Done in {elapsed:.1f}s — "
            f"checked={result['checked']}, "
            f"triggered={result['triggered']}, "
            f"expired={result['expired']}"
        )
    except Exception as e:
        print(f"[INTRADAY] Error: {e}")
        raise


if __name__ == "__main__":
    lock_fd = acquire_lock()
    if lock_fd is None:
        print("[INTRADAY] Another instance is running — exiting")
        sys.exit(0)

    try:
        asyncio.run(main())
    finally:
        release_lock(lock_fd)

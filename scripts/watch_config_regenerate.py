"""Watch `src/config.py` and run regeneration when it changes.

Usage:
    python scripts/watch_config_regenerate.py

This simple watcher polls the file mtime and runs the regeneration script
when it detects a change. It is intentionally dependency-free so you can run
it in the development environment.
"""
import os
import time
import subprocess
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "src", "config.py")
REGEN_SCRIPT = os.path.join(PROJECT_ROOT, "src", "tests", "regenerate_all_htmls.py")


def run_regen():
    print("[watch] Detected config change — regenerating outputs...")
    env = os.environ.copy()
    # Ensure PYTHONPATH includes project src
    env["PYTHONPATH"] = env.get("PYTHONPATH", "") + os.pathsep + os.path.join(PROJECT_ROOT, "src")
    cmd = [sys.executable, REGEN_SCRIPT]
    proc = subprocess.Popen(cmd, env=env)
    proc.communicate()
    if proc.returncode == 0:
        print("[watch] Regeneration completed.")
    else:
        print(f"[watch] Regeneration failed (exit {proc.returncode}).")


def watch(poll_sec: float = 1.0):
    if not os.path.exists(CONFIG_PATH):
        print(f"Config not found: {CONFIG_PATH}")
        return
    last_mtime = os.path.getmtime(CONFIG_PATH)
    print(f"[watch] Monitoring {CONFIG_PATH} for changes. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(poll_sec)
            try:
                m = os.path.getmtime(CONFIG_PATH)
            except FileNotFoundError:
                continue
            if m != last_mtime:
                last_mtime = m
                run_regen()
    except KeyboardInterrupt:
        print("[watch] Stopped by user.")


if __name__ == "__main__":
    watch()

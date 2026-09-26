#!/usr/bin/env python3
"""
Aegis Sovereign Desktop Edition — Compatibility Watcher Wrapper (ADR-37).
Exposes WorkstationDaemon and WorkstationWatcherHandler backed by the production daemon.
"""

from .daemon import (
    WorkstationDaemon,
    WorkstationWatcherHandler,
    DesktopHUDHandler,
    SlidingDebouncer,
    get_default_cache_dir,
    read_file_readonly,
    run_daemon,
    DEFAULT_STORAGE_DIR if 'DEFAULT_STORAGE_DIR' in locals() else None,
)

__all__ = [
    "WorkstationDaemon",
    "WorkstationWatcherHandler",
    "DesktopHUDHandler",
    "SlidingDebouncer",
    "get_default_cache_dir",
    "read_file_readonly",
    "run_daemon",
]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Aegis Sovereign Desktop Workstation Daemon")
    parser.add_argument("--watch", nargs="*", help="Folders to watch and index in-place")
    parser.add_argument("--port", type=int, default=9876, help="Local loopback port for HUD")
    args = parser.parse_args()
    run_daemon(watch_paths=args.watch, port=args.port)

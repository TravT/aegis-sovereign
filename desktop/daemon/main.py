#!/usr/bin/env python3
"""
Entrypoint for Aegis Sovereign Desktop & NanoRunner IPC Daemon (`python3 -m desktop.daemon.main`).
"""
import argparse
from desktop.daemon.daemon import run_daemon


def main():
    parser = argparse.ArgumentParser(description="Aegis Sovereign Desktop & NanoRunner IPC Daemon")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8766, help="Bind port (default: 8766)")
    parser.add_argument("--watch", nargs="*", default=[], help="Directories to watch in-place")
    args = parser.parse_args()
    run_daemon(watch_paths=args.watch, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

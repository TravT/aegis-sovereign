"""
Entrypoint for python3 -m core.server
"""

import argparse
from . import run_server, DEFAULT_HOST, DEFAULT_PORT

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sovereign Core REST & Ingestion Server")
    parser.add_argument("--host", type=str, default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    run_server(host=args.host, port=args.port)

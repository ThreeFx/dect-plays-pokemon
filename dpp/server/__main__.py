"""Run the server: DPP_PASSWORD=... python -m dpp.server"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from waitress import serve

from . import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/server.sqlite3"))
    parser.add_argument("--rom", type=Path, default=Path("pokemon-firered.gba"), help="the game ROM, for Pokémon icons")
    parser.add_argument("--host", default="127.0.0.1", help="address to listen on; 0.0.0.0 for all interfaces")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    password = os.environ.get("DPP_PASSWORD")
    if not password:
        sys.exit("Set the admin password in the DPP_PASSWORD environment variable.")
    args.database.parent.mkdir(parents=True, exist_ok=True)
    rom = args.rom if args.rom.exists() else None
    if rom is None:
        print(f"no ROM at {args.rom}: the admin page will show party names instead of icons")
    print(f"listening on http://{args.host}:{args.port}, database {args.database}")
    serve(create_app(args.database, password, rom), host=args.host, port=args.port)


if __name__ == "__main__":
    main()

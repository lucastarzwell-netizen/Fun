"""Command line: `house-agent serve | import <seed.json> | run <profile_id>`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="house-agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run the API server (and scheduler)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    imp = sub.add_parser("import", help="Import a profile + listings from a seed JSON file")
    imp.add_argument("path", type=Path)

    run = sub.add_parser("run", help="Run a search profile now, in the foreground")
    run.add_argument("profile_id", type=int)

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("house_agent.main:app", host=args.host, port=args.port, reload=args.reload)
        return

    from .auth import ensure_default_user
    from .db import SessionLocal, init_db

    init_db()
    with SessionLocal() as session:
        user = ensure_default_user(session)
        if args.cmd == "import":
            from .importer import import_seed

            profile = import_seed(session, user, args.path)
            print(f"Imported profile {profile.id}: {profile.name}")
        elif args.cmd == "run":
            from .agent.runner import create_run, execute_run
            from .models import SearchProfile

            profile = session.get(SearchProfile, args.profile_id)
            if profile is None:
                parser.error(f"No profile {args.profile_id}")
            run = execute_run(session, create_run(session, profile, "manual").id)
            print(json.dumps({"status": run.status, **run.summary}, indent=2))


if __name__ == "__main__":
    main()

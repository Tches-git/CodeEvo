"""Seed a clearly marked local demo database and start CodeEvo without an LLM."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from codeevo.annotation_demo import seed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run CodeEvo locally with offline annotation demo records"
    )
    parser.add_argument(
        "--database", default="output/codeevo-demo.db",
        help="Disposable SQLite database path (default: output/codeevo-demo.db)",
    )
    args = parser.parse_args()
    database = Path(args.database).expanduser().resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    created = seed(str(database))

    # An explicit local provider must win over stale model fields in a developer .env.
    os.environ["CODEEVO_DB_PATH"] = str(database)
    os.environ["CODEEVO_LLM_PROVIDER"] = "local"
    os.environ["CODEEVO_AUTH_REQUIRED"] = "false"

    from codeevo.api import run

    print("seeded %d new demo cases in %s" % (created, database))
    print("opening CodeEvo at http://127.0.0.1:8080")
    run()


if __name__ == "__main__":
    main()

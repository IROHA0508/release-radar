"""Command line: python -m backend {update,detect,selftest}

  update    Detect new posts, summarize them with the Claude API and update data/ (needs ANTHROPIC_API_KEY;
            without it, only detection runs and candidates go to backend/state/pending.json).
  detect    Print new-post candidates without changing any file (no API key needed).
  selftest  Check every source still works: hide the newest known article per company and confirm it is found.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["update", "detect", "selftest"])
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "selftest":
        ok, _ = pipeline.run_selftest()
        return 0 if ok else 1

    report = pipeline.run_update(dry_run=args.command == "detect")
    print(json.dumps(report.__dict__, ensure_ascii=False, indent=2))
    # Failed articles are retried on the next run, so the command still succeeds and the
    # workflow can commit lastChecked and the run state.
    return 0


if __name__ == "__main__":
    sys.exit(main())

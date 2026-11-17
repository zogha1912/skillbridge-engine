"""Run the taxonomy pipeline steps in order: ESCO -> O*NET -> crosswalk -> embeddings.

Run with: python -m etl.pipeline [--only STEP ...] [--skip STEP ...] [--scope ict|all]

A lightweight stand-in for an Airflow DAG (see docs/02-architecture.md §6): every step
is idempotent, so the whole pipeline can simply be re-run. Stops at the first failing
step. Exit codes: 0 = all done, 1 = a step failed, 2 = embeddings stopped at the
Gemini daily quota (progress saved; run again after the reset).
"""

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

from etl import crosswalk_import, embed, esco_import, onet_import

Step = Callable[[list[str]], Awaitable[int]]
STEP_ORDER = ("esco", "onet", "crosswalk", "embed")
QUOTA_EXIT = 2


def build_steps(scope: str) -> dict[str, tuple[Step, list[str]]]:
    return {
        "esco": (esco_import.main, ["--scope", scope]),
        "onet": (onet_import.main, ["--scope", scope]),
        "crosswalk": (crosswalk_import.main, []),
        "embed": (embed.main, []),
    }


def select_steps(only: list[str] | None, skip: list[str] | None) -> list[str]:
    chosen = [s for s in STEP_ORDER if not only or s in only]
    return [s for s in chosen if not skip or s not in skip]


async def run(step_names: list[str], scope: str) -> int:
    steps = build_steps(scope)
    for name in step_names:
        func, argv = steps[name]
        started = time.monotonic()
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] step {name}: start", flush=True)
        code = await func(argv)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] step {name}: exit {code} ({time.monotonic() - started:.0f}s)", flush=True)
        if code == QUOTA_EXIT and name == "embed":
            return QUOTA_EXIT
        if code != 0:
            print(f"Pipeline stopped: step '{name}' failed.", flush=True)
            return 1
    print("Pipeline finished.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="+", choices=STEP_ORDER, help="run only these steps")
    parser.add_argument("--skip", nargs="+", choices=STEP_ORDER, help="skip these steps")
    parser.add_argument("--scope", choices=("ict", "all"), default="ict")
    args = parser.parse_args(argv)
    return asyncio.run(run(select_steps(args.only, args.skip), args.scope))


if __name__ == "__main__":
    sys.exit(main())

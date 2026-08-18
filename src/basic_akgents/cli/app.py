"""The console application: start the plumbing, hand it to the prompt, clean up.

Three things live for as long as the program does and are wired here: the feed
that watches the messages of every team, the `CaseRunner` that owns the teams,
and the `ConsoleSession` that turns typed lines into calls on those two.
"""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from basic_akgents.case_runner import CaseRunner
from basic_akgents.cli import console
from basic_akgents.cli.event_feed import EventFeed
from basic_akgents.cli.session import ConsoleSession

# Resolved from this file (src/basic_akgents/cli/app.py), so the event store
# always lands in <project>/data no matter which working directory the demo is
# started from.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVENT_STORE_DIR = PROJECT_ROOT / "data"

# One readable line per captured message, next to the per-team streams the
# framework writes. A `tail -f` on this file is the second panel of the demo.
LIVE_FEED_LOG = EVENT_STORE_DIR / "live-feed.log"


def parse_args() -> argparse.Namespace:
    """Read the case to start with and how much of the feed to show."""
    parser = argparse.ArgumentParser(
        description="Handle cases with a team of agents, one team per case."
    )
    parser.add_argument("case_id", nargs="?", help="Identifier of the case to start with.")
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Echo every message of a team as it arrives, same as the 'follow' command.",
    )
    parser.add_argument(
        "--no-feed-log",
        action="store_true",
        help=f"Do not write the live feed to {LIVE_FEED_LOG.name}.",
    )
    return parser.parse_args()


def main() -> None:
    """Run cases and look at teams until the human stops asking."""
    args = parse_args()
    requester_id = getpass.getuser()

    feed = EventFeed(
        log_path=None if args.no_feed_log else LIVE_FEED_LOG,
        following=args.follow,
    )
    feed.start()

    console.print_intro(EVENT_STORE_DIR, feed.log_path)

    try:
        # The tap goes to every team the runner creates or resumes.
        with CaseRunner(EVENT_STORE_DIR, subscribers=[feed.tap]) as runner:
            ConsoleSession(runner, feed, requester_id).run(args.case_id)
    finally:
        feed.stop()


if __name__ == "__main__":
    main()

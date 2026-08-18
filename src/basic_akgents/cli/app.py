"""The console application: read a case id, run it, show the outcome, repeat."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from basic_akgents.case_repository import DEMO_CASES
from basic_akgents.case_runner import CaseRunner
from basic_akgents.case_team_card import ANY_CASE_ID, case_team_card
from basic_akgents.cli import console
from basic_akgents.cli.cli_user_proxy import CliUserProxyAgent
from basic_akgents.cli.prompts import ask_for_case_id

# Resolved from this file (src/basic_akgents/cli/app.py), so the event store
# always lands in <project>/data no matter which working directory the demo is
# started from.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
EVENT_STORE_DIR = PROJECT_ROOT / "data"


def parse_args() -> argparse.Namespace:
    """Read the first case id from the command line, or ask for it."""
    parser = argparse.ArgumentParser(description="Handle cases with a team of agents, one team per case.")
    parser.add_argument("case_id", nargs="?", help="Identifier of the case to start with.")
    return parser.parse_args()


def main() -> None:
    """Run cases until the human stops asking for them."""
    args = parse_args()
    requester_id = getpass.getuser()

    console.print_demo_cases(DEMO_CASES)

    # The layout is the same for every case, so show it once with a stand-in id.
    console.print_team(case_team_card(case_id=ANY_CASE_ID, proxy_class=CliUserProxyAgent))

    with CaseRunner(EVENT_STORE_DIR, proxy_class=CliUserProxyAgent) as runner:
        case_id = args.case_id or ask_for_case_id()

        while case_id is not None:
            console.print_case_result(runner.run_case(case_id, requester_id))
            case_id = ask_for_case_id()


if __name__ == "__main__":
    main()

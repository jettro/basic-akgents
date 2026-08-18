"""Every `print` of the demo, so the rest of the code has none.

Pure rendering: these functions are given data and turn it into lines on the
terminal. Skip this file when reading the repository for the framework concepts.
"""

from __future__ import annotations

from collections.abc import Iterable

from akgentic.team import TeamCard, TeamCardMember

from basic_akgents.case_repository import Case
from basic_akgents.case_runner import CaseRunResult


def print_demo_cases(cases: Iterable[Case]) -> None:
    """Show what is in the case system, priority 0 means it still needs triage.

    Args:
        cases: Cases the demo store is seeded with.
    """
    print("Cases in the demo store:")
    for case in cases:
        print(f"  {case.case_id} : priority {case.case_priority.label:<12} {case.case_description}")


def print_member_tree(member: TeamCardMember, indent: int = 0) -> None:
    """Print a `TeamCardMember` tree with indentation.

    Args:
        member: Member to print, children included.
        indent: Current nesting level.
    """
    prefix = "  " * indent
    role = member.card.role
    name = member.card.config.name
    hc = member.headcount
    subs = len(member.members)
    print(f"{prefix}- {name} (role={role}, headcount={hc}, subordinates={subs})")
    for child in member.members:
        print_member_tree(child, indent + 1)


def print_team(team_card: TeamCard) -> None:
    """Show the shape of the team that is created per case.

    Args:
        team_card: Card describing the team.
    """
    print(f"\nTeam: {team_card.name}")
    print("Entry point:")
    print_member_tree(team_card.entry_point, indent=1)
    print("Members:")
    for member in team_card.members:
        print_member_tree(member, indent=1)


def print_case_result(result: CaseRunResult) -> None:
    """Tell the human how the team finished, or that it did not.

    Args:
        result: Outcome of one case run.
    """
    if result.event is None:
        print(f"\n[Case {result.case_id}] Timed out waiting for the case to be handled.")
    else:
        print(
            f"\n[Case {result.event.case_id}] {result.event.outcome}, priority {result.event.case_priority.label}"
        )

    print(
        f"=== {result.message_count} messages, {result.state_count} agent states, team {result.team_id} ==="
    )

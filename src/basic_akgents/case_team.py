"""Who is who in a case team, and how a member finds a colleague.

The names below are the single source of truth: `case_team_card` puts them on the
agent cards, and the agents use them to look each other up. Nobody has to be
handed an address, so a team that is resumed from its card needs no wiring at all.
"""

from __future__ import annotations

from typing import Any

from akgentic.core import ActorAddress, Akgent
from akgentic.core.agent import WarningError

from basic_akgents.case_model import CaseMetaData

CASE_COORDINATOR = "@CaseCoordinator"
CASE_TRIAGE = "@CaseTriage"
CASE_REPOSITORY = "@CaseRepository"
USER_PROXY = "@UserProxy"


def find_team_member(agent: Akgent[Any, Any], name: str) -> ActorAddress:
    """Look a colleague up in the team roster of the orchestrator.

    Do this while handling a message, never from `on_start`: children are
    created through the mailbox of their parent, so a parent is already running
    before its children are on the roster.

    Args:
        agent: Agent doing the lookup.
        name: Name of the colleague, `@` prefix included.

    Returns:
        Address of the colleague.

    Raises:
        WarningError: If the team has no member with this name.
    """
    address = agent.get_team_member(name)

    if address is None:
        raise WarningError(f"No {name} in the team of {agent.config.name}.")

    return address


def find_team_case_id(agent: Akgent[Any, Any]) -> str:
    """Look up the case ID of the team.

    Args:
        agent: Agent doing the lookup.

    Returns:
        Case ID of the team.
    """

    case_metadata: CaseMetaData = agent.orchestrator_proxy_ask.get_metadata()
    if case_metadata is None or case_metadata.case_id is None:
        raise WarningError(f"No case metadata and case_id in the team of {agent.config.name}.")
    return case_metadata.case_id
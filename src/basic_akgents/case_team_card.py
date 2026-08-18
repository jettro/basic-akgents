"""How a case team is described: one `AgentCard` per role, nested into a `TeamCard`.

The card is the whole declaration of a team: who is in it, who receives the
first message, which message types travel through it and what metadata it is
indexed by. `TeamManager` creates the actors from it, and can resume the team
later from the same description.
"""

from __future__ import annotations

from akgentic.core import AgentCard, BaseConfig, UserProxy
from akgentic.team import TeamCard, TeamCardMember

from basic_akgents.case_coordinator import CaseCoordinatorAgent, CaseCoordinatorConfig, HandleCaseRequest
from basic_akgents.case_model import CaseMetaData
from basic_akgents.case_repository import DEFAULT_CASE_REPOSITORY
from basic_akgents.case_repository_agent import CaseRepositoryAgent, CaseRepositoryConfig
from basic_akgents.case_team import CASE_COORDINATOR, CASE_REPOSITORY, CASE_TRIAGE, USER_PROXY
from basic_akgents.case_triage import CaseTriageAgent, CaseTriageConfig

# Stand-in id for showing the layout before a case has been picked: the shape of
# the team is the same for every case.
ANY_CASE_ID = "<case id>"


def case_team_card(case_id: str, proxy_class: type[UserProxy]) -> TeamCard:
    """Describe the team that handles a single case.

    The human bridge is passed in rather than hard-coded, so this description
    stays free of any console code: a CLI hands in its stdin proxy, a web front
    end would hand in its own.

    Args:
        case_id: Case every agent of the team works on.
        proxy_class: `UserProxy` subclass that talks to the human.

    Returns:
        Card `TeamManager` creates or resumes the team from.
    """
    proxy_card = AgentCard(
        description="Bridge between the team and the human at the console.",
        skills=["ask_human"],
        agent_class=proxy_class,
        config=BaseConfig(name=USER_PROXY, role="UserProxy"),
    )

    coordinator_card: AgentCard = AgentCard(
        description="Orchestrate the case handling.",
        skills=["coordinate"],
        agent_class=CaseCoordinatorAgent,
        config=CaseCoordinatorConfig(name=CASE_COORDINATOR, role="Coordinator", case_id=case_id),
    )

    triage_agent_card: AgentCard = AgentCard(
        description="Triage the case and assign it to the appropriate agent.",
        skills=["triage"],
        agent_class=CaseTriageAgent,
        config=CaseTriageConfig(name=CASE_TRIAGE, role="Triage", case_id=case_id),
    )

    repository_agent_card: AgentCard = AgentCard(
        description="Access cases through a repository.",
        skills=["repository"],
        agent_class=CaseRepositoryAgent,
        config=CaseRepositoryConfig(
            name=CASE_REPOSITORY,
            role="Repository",
            case_id=case_id,
            backend=DEFAULT_CASE_REPOSITORY,
        ),
    )

    triage_member = TeamCardMember(card=triage_agent_card)
    repository_member = TeamCardMember(card=repository_agent_card)
    coordinator_member = TeamCardMember(card=coordinator_card, members=[triage_member, repository_member])
    human_member = TeamCardMember(card=proxy_card)

    return TeamCard(
        name="case-handling-team",
        description="Handles cases when requested using an id.",
        entry_point=human_member,
        members=[
            coordinator_member,
        ],
        # Required for runtime.send(str): the first type is what a plain string is
        # wrapped in. Without it, send() raises RuntimeError.
        message_types=[HandleCaseRequest],
        metadata_type=CaseMetaData,
        welcome_message=f"Case team ready for {case_id}",
    )

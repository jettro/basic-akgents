import argparse
import getpass
import threading
import time
from pathlib import Path

from akgentic.core import ActorAddress, ActorSystem, BaseConfig, Orchestrator, AgentCard
from akgentic.team import TeamCard, TeamCardMember, TeamFactory, YamlEventStore, TeamManager, TeamRuntime

from basic_akgents.case_coordinator import CaseCoordinatorConfig, CaseCoordinatorAgent, HandleCaseRequest
from basic_akgents.case_model import CaseMetaData
from basic_akgents.case_repository import DEMO_CASES, CaseRepository, DummyCaseRepository
from basic_akgents.case_repository_agent import CaseRepositoryAgent, CaseRepositoryConfig
from basic_akgents.case_triage import CaseTriageAgent, CaseTriageConfig
from basic_akgents.cli_user_proxy import CliUserProxyAgent

# The human answers on stdin, so give the conversation room before giving up.
CASE_TIMEOUT_SECONDS = 300.0

# Resolved from this file, so the event store always lands in <project>/runtime
# no matter which working directory the demo is started from.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENT_STORE_DIR = PROJECT_ROOT / "data"


def parse_args() -> argparse.Namespace:
    """Read the case id from the command line, or ask for it."""
    parser = argparse.ArgumentParser(description="Handle a single case with a team of agents.")
    parser.add_argument("case_id", nargs="?", help="Identifier of the case to work on.")
    return parser.parse_args()


def print_demo_cases() -> None:
    """Show what is in the case system, priority 0 means it still needs triage."""
    print("Cases in the demo store:")
    for case in DEMO_CASES:
        print(f"  {case.case_id} : priority {case.case_priority.label:<12} {case.case_description}")


def create_team(case_id: str) -> TeamCard:
    proxy_card = AgentCard(
        description="Bridge between the team and the human at the console.",
        skills=["ask_human"],
        agent_class=CliUserProxyAgent,
        config=BaseConfig(name="@UserProxy", role="UserProxy"),
    )

    coordinator_card: AgentCard = AgentCard(
        description="Orchestrate the case handling.",
        skills=["coordinate"],
        agent_class=CaseCoordinatorAgent,
        config=CaseCoordinatorConfig(name="@CaseCoordinator", role="Coordinator", case_id=case_id),
    )

    triage_agent_card: AgentCard = AgentCard(
        description="Triage the case and assign it to the appropriate agent.",
        skills=["triage"],
        agent_class=CaseTriageAgent,
        config=CaseTriageConfig(name="@CaseTriage", role="Triage", case_id=case_id),
    )

    repository_agent_card: AgentCard = AgentCard(
        description="Access cases through a repository.",
        skills=["repository"],
        agent_class=CaseRepositoryAgent,
        config=CaseRepositoryConfig(name="@CaseRepository", role="Repository", case_id=case_id),
    )

    triage_member = TeamCardMember(card=triage_agent_card)
    repository_member = TeamCardMember(card=repository_agent_card)
    coordinator_member = TeamCardMember(card=coordinator_card, members=[triage_member, repository_member])
    human_member = TeamCardMember(card=proxy_card)

    return TeamCard(
        name="case-handling-team", description="Handles cases when requested using an id.",
        entry_point=human_member,
        members=[
            coordinator_member,
        ],
        # Required for runtime.send(str): the first type is what a plain string is
        # wrapped in. Without it, send() raises RuntimeError.
        message_types=[HandleCaseRequest],
        metadata_type=CaseMetaData,
        welcome_message=f"Case team ready for {case_id}"
    )


def print_tree(member: TeamCardMember, indent: int = 0) -> None:
    """Print a TeamCardMember tree with indentation."""
    prefix = "  " * indent
    role = member.card.role
    name = member.card.config.name
    hc = member.headcount
    subs = len(member.members)
    print(f"{prefix}- {name} (role={role}, headcount={hc}, subordinates={subs})")
    for child in member.members:
        print_tree(child, indent + 1)

def wire_live_dependencies(
    actor_system: ActorSystem,
    runtime: TeamRuntime,
    case_repository: CaseRepository,
    case_handled: threading.Event,
) -> None:
    """Hand live objects over by reference; config/state are serialized, these cannot be."""
    addrs = runtime.addrs

    actor_system.proxy_tell(addrs["@CaseRepository"], CaseRepositoryAgent).set_case_repository(case_repository)
    actor_system.proxy_tell(addrs["@CaseTriage"], CaseTriageAgent).set_repository_agent(addrs["@CaseRepository"])
    actor_system.proxy_tell(addrs["@CaseCoordinator"], CaseCoordinatorAgent).set_agents(
        triage_agent_address=addrs["@CaseTriage"],
        user_proxy_address=addrs["@UserProxy"],
    )
    actor_system.proxy_tell(addrs["@UserProxy"], CliUserProxyAgent).set_completion_event(case_handled)


def main() -> None:
    args = parse_args()

    if args.case_id is None:
        print_demo_cases()

    case_id = args.case_id or input("Case id: ").strip() or "case_1"
    requester_id = getpass.getuser()

    team_card: TeamCard = create_team(case_id=case_id)
    case_repository: CaseRepository = DummyCaseRepository()
    case_handled = threading.Event()

    actor_system = ActorSystem()
    event_store = YamlEventStore(EVENT_STORE_DIR)
    manager = TeamManager(actor_system=actor_system, event_store=event_store)
    runtime: TeamRuntime | None = None

    print(f"Team: {team_card.name}")
    print("Entry point:")
    print_tree(team_card.entry_point, indent=1)
    print("Members:")
    for member in team_card.members:
        print_tree(member, indent=1)

    # Composition root: pick the implementation here, only @CaseRepository ever
    # holds it. Swap in a database backed one without touching any agent.

    try:
        runtime = manager.create_team(team_card=team_card, user_id=requester_id, metadata=CaseMetaData(case_id=case_id))

        wire_live_dependencies(actor_system, runtime, case_repository, case_handled)


        runtime.send(HandleCaseRequest(requester_id=requester_id))
        if not case_handled.wait(timeout=CASE_TIMEOUT_SECONDS):
            print(f"[Case {case_id}] Timed out waiting for the case to be handled.")

        messages = runtime.orchestrator_proxy.get_messages()
        states = runtime.orchestrator_proxy.get_states()
        print(f"\n=== {len(messages)} messages, {len(states)} agent states, team {runtime.id} ===")

    finally:
        if runtime is not None:
            manager.stop_team(runtime.id)  # marks the Process STOPPED -> resumable

        actor_system.shutdown(timeout=5)


if __name__ == "__main__":
    main()

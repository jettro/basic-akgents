import argparse
import getpass
import queue
import time
import uuid
from pathlib import Path

from akgentic.core import ActorSystem, BaseConfig, AgentCard
from akgentic.team import TeamCard, TeamCardMember, YamlEventStore, TeamManager

from basic_akgents.case_closed_subscriber import CaseClosedSubscriber, ClosedQueue
from basic_akgents.case_coordinator import CaseCoordinatorConfig, CaseCoordinatorAgent, HandleCaseRequest
from basic_akgents.case_events import CaseClosed
from basic_akgents.case_model import CaseMetaData
from basic_akgents.case_repository import DEMO_CASES, DEFAULT_CASE_REPOSITORY
from basic_akgents.case_repository_agent import CaseRepositoryAgent, CaseRepositoryConfig
from basic_akgents.case_team import CASE_COORDINATOR, CASE_REPOSITORY, CASE_TRIAGE, USER_PROXY
from basic_akgents.case_triage import CaseTriageAgent, CaseTriageConfig
from basic_akgents.cli_user_proxy import CliUserProxyAgent

# The human answers on stdin, so give the conversation room before giving up.
CASE_TIMEOUT_SECONDS = 300.0

# Resolved from this file, so the event store always lands in <project>/runtime
# no matter which working directory the demo is started from.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVENT_STORE_DIR = PROJECT_ROOT / "data"


def parse_args() -> argparse.Namespace:
    """Read the first case id from the command line, or ask for it."""
    parser = argparse.ArgumentParser(description="Handle cases with a team of agents, one team per case.")
    parser.add_argument("case_id", nargs="?", help="Identifier of the case to start with.")
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


def print_team(team_card: TeamCard) -> None:
    """Show the shape of the team that is created per case."""
    print(f"\nTeam: {team_card.name}")
    print("Entry point:")
    print_tree(team_card.entry_point, indent=1)
    print("Members:")
    for member in team_card.members:
        print_tree(member, indent=1)


def ask_for_case_id() -> str | None:
    """Ask which case is next.

    Returns:
        The case id, or None when the human wants to stop.
    """
    try:
        answer = input("\nCase id (empty to quit): ").strip()
    except EOFError:
        return None

    return None if answer in ("", "q", "quit") else answer


def await_case(closed: ClosedQueue, team_id: uuid.UUID) -> CaseClosed | None:
    """Wait until the team announces its case as closed.

    Filters on `team_id`: a team that timed out earlier may still deliver, and
    such a late event must not be read as the answer of the current team.

    Args:
        closed: Queue the subscriber publishes every closed case on.
        team_id: Team being waited for.

    Returns:
        The event, or None when the team stayed silent long enough.
    """
    deadline = time.monotonic() + CASE_TIMEOUT_SECONDS

    while (remaining := deadline - time.monotonic()) > 0:
        try:
            closed_team_id, event = closed.get(timeout=remaining)
        except queue.Empty:
            return None

        if closed_team_id == team_id:
            return event

    return None


def handle_case(
    manager: TeamManager,
    closed: ClosedQueue,
    case_id: str,
    requester_id: str,
) -> None:
    """Run one case in a team of its own, from request to closing report.

    A team needs no wiring at all: colleagues are looked up by name, the case
    store is built by `@CaseRepository` from the backend in its config, and the
    end of the case arrives here as a `CaseClosed` event.

    Args:
        manager: Manager that owns the lifecycle of the teams.
        closed: Queue the shared subscriber publishes closed cases on.
        case_id: Case to work on.
        requester_id: Human asking for the case to be handled.
    """
    runtime = manager.create_team(
        team_card=create_team(case_id=case_id),
        user_id=requester_id,
        metadata=CaseMetaData(case_id=case_id),
    )

    try:
        runtime.send(HandleCaseRequest(requester_id=requester_id))
        report_outcome(case_id, await_case(closed, runtime.id))

        messages = runtime.orchestrator_proxy.get_messages()
        states = runtime.orchestrator_proxy.get_states()
        print(f"=== {len(messages)} messages, {len(states)} agent states, team {runtime.id} ===")
    finally:
        # Marks the Process STOPPED -> resumable, and waits for every mailbox to
        # drain: that barrier keeps the last output of this team out of the next
        # prompt, and stops two @UserProxy actors from competing for stdin.
        manager.stop_team(runtime.id)


def report_outcome(case_id: str, event: CaseClosed | None) -> None:
    """Tell the human how the team finished, or that it did not.

    Args:
        case_id: Case the team worked on.
        event: Closing event of the team, None when it stayed silent.
    """
    if event is None:
        print(f"\n[Case {case_id}] Timed out waiting for the case to be handled.")
        return

    print(f"\n[Case {event.case_id}] {event.outcome}, priority {event.case_priority.label}")


def main() -> None:
    args = parse_args()
    requester_id = getpass.getuser()

    # Filled by the subscriber on the actor thread of an orchestrator, read here
    # on the thread that owns the lifecycle of the teams.
    closed: ClosedQueue = queue.Queue()

    actor_system = ActorSystem()
    manager = TeamManager(
        actor_system=actor_system,
        event_store=YamlEventStore(EVENT_STORE_DIR),
        # Shared by every team of this run, so it routes on team_id.
        subscribers=[CaseClosedSubscriber(closed)],
    )

    print_demo_cases()

    # The layout is the same for every case, so show it once with a stand-in id.
    print_team(create_team(case_id="<case id>"))

    case_id = args.case_id or ask_for_case_id()

    try:
        while case_id is not None:
            handle_case(manager, closed, case_id, requester_id)
            case_id = ask_for_case_id()
    finally:
        actor_system.shutdown(timeout=5)


if __name__ == "__main__":
    main()

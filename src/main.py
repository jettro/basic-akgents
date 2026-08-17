import argparse
import getpass
import threading

from akgentic.core import ActorAddress, ActorSystem, BaseConfig, Orchestrator

from basic_akgents.case_coordinator import CaseCoordinatorConfig, CaseCoordinatorAgent, HandleCaseRequest
from basic_akgents.case_repository import DEMO_CASES, CaseRepository, DummyCaseRepository
from basic_akgents.case_repository_agent import CaseRepositoryAgent, CaseRepositoryConfig
from basic_akgents.case_triage import CaseTriageAgent, CaseTriageConfig
from basic_akgents.cli_user_proxy import CliUserProxyAgent

# The human answers on stdin, so give the conversation room before giving up.
CASE_TIMEOUT_SECONDS = 300.0


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


def main() -> None:
    args = parse_args()

    if args.case_id is None:
        print_demo_cases()

    case_id = args.case_id or input("Case id: ").strip() or "case_1"
    requester_id = getpass.getuser()

    # Composition root: pick the implementation here, only @CaseRepository ever
    # holds it. Swap in a database backed one without touching any agent.
    case_repository: CaseRepository = DummyCaseRepository()

    actor_system = ActorSystem()

    try:
        # The Orchestrator is a real agent and must be created explicitly as the root
        # actor. ActorSystem.createActor does NOT attach one, so anything created
        # directly on the actor system ends up without telemetry ("no orchestrator").
        orchestrator_addr: ActorAddress = actor_system.createActor(
            Orchestrator,
            config=BaseConfig(name="@Orchestrator", role="Orchestrator"),
        )
        orchestrator = actor_system.proxy_ask(orchestrator_addr, Orchestrator)

        # Let the orchestrator create the root agent: Akgent.createActor is the only
        # call that propagates the orchestrator address (and team_id/parent) down.
        coordinator_addr: ActorAddress = orchestrator.createActor(
            CaseCoordinatorAgent,
            config=CaseCoordinatorConfig(name="@CaseCoordinator",
                                         role="Coordinator",
                                         case_id=case_id),
        )
        coordinator = actor_system.proxy_ask(coordinator_addr, CaseCoordinatorAgent)

        # Created by the coordinator, so they are children of the coordinator and
        # inherit the same orchestrator and team_id.
        triage_agent_address: ActorAddress = coordinator.createActor(
            CaseTriageAgent,
            config=CaseTriageConfig(name="@CaseTriage", role="Triage", case_id=case_id),
        )
        repository_agent_address: ActorAddress = coordinator.createActor(
            CaseRepositoryAgent,
            config=CaseRepositoryConfig(name="@CaseRepository", role="Repository", case_id=case_id),
        )
        user_proxy_address: ActorAddress = coordinator.createActor(
            CliUserProxyAgent,
            config=BaseConfig(name="@UserProxy", role="UserProxy"),
        )

        coordinator.set_agents(triage_agent_address=triage_agent_address,
                               user_proxy_address=user_proxy_address)

        # Case data goes through one agent, so triage only needs its address.
        actor_system.proxy_tell(triage_agent_address, CaseTriageAgent).set_repository_agent(
            repository_agent_address)

        # Hand the repository over by reference. proxy_tell is a plain method call,
        # so the live object never passes through serialization.
        actor_system.proxy_tell(repository_agent_address,
                                CaseRepositoryAgent).set_case_repository(case_repository)

        # The user proxy signals this event once it received the final result, so we
        # do not have to guess how long the human needs to type.
        case_handled = threading.Event()
        actor_system.proxy_tell(user_proxy_address, CliUserProxyAgent).set_completion_event(case_handled)

        print(f"[Case {case_id}] Team started. Triage assesses the case, you approve its priority.")
        actor_system.tell(coordinator_addr, HandleCaseRequest(requester_id=requester_id))

        # Wait for the workflow to complete
        if not case_handled.wait(timeout=CASE_TIMEOUT_SECONDS):
            print(f"[Case {case_id}] Timed out waiting for the case to be handled.")

        # Query orchestrator for telemetry
        team = orchestrator.get_team()
        messages = orchestrator.get_messages()
        states = orchestrator.get_states()

        # Print summary
        print("")
        print("=== Orchestrator Summary ===")
        print(f"Total messages: {len(messages)}")
        print(f"Team members: {len(team)} agents")
        print(f"State snapshots: {len(states)} agents tracked")
        print("===========================")

        print("[Multi-Agent] Demo complete. Shutting down.")
    finally:
        actor_system.shutdown(timeout=5)

if __name__ == "__main__":
    main()

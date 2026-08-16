import time

from akgentic.core import ActorAddress, ActorSystem, BaseConfig, Orchestrator

from basic_akgents.case_coordinator import CaseCoordinatorConfig, CaseCoordinatorAgent, HandleCaseRequest
from basic_akgents.case_triage import CaseTriageAgent, CaseTriageConfig


def main() -> None:
    case_id = "case_1"
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

        # Created by the coordinator, so it is a child of the coordinator and
        # inherits the same orchestrator and team_id.
        triage_agent_address: ActorAddress = coordinator.createActor(
            CaseTriageAgent,
            config=CaseTriageConfig(name="@CaseTriage", role="Triage", case_id=case_id),
        )

        coordinator.set_agents(triage_agent_address=triage_agent_address)

        actor_system.tell(coordinator_addr, HandleCaseRequest())

        # Wait for the workflow to complete
        time.sleep(1.5)

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

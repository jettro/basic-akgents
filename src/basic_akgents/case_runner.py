"""Running cases, one short-lived team per case.

Everything with a lifecycle lives here: the `ActorSystem`, the `TeamManager`
with its event store, and the subscriber that reports a case as closed. A team
is created for a single case and stopped again as soon as that case is done,
which is what teams in this framework are for.

A stopped team is not gone: its card, its metadata, its events and the last state
of every agent stay in the event store. That makes this class the reading side as
well - `list_teams`, `load_events`, `load_agent_states` - and `resume_case` puts
such a team back together and gives it work again.

Nothing here prints: the console layer decides how to show a result, this layer
only produces one.
"""

from __future__ import annotations

import queue
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from akgentic.core import ActorSystem, EventSubscriber
from akgentic.team import (
    AgentStateSnapshot,
    PersistedEvent,
    Process,
    TeamManager,
    TeamRuntime,
    TeamStatus,
    YamlEventStore,
)

from basic_akgents.case_closed_subscriber import CaseClosedSubscriber, ClosedQueue
from basic_akgents.case_coordinator import HandleCaseRequest
from basic_akgents.case_events import CaseClosed
from basic_akgents.case_model import CaseMetaData, case_id_of
from basic_akgents.case_team_card import case_team_card

# The human answers on stdin, so give the conversation room before giving up.
CASE_TIMEOUT_SECONDS = 300.0

# Grace period for the actor system to stop everything that is still running.
SHUTDOWN_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class CaseRunResult:
    """What one case run produced, ready to be reported to a human.

    Attributes:
        case_id: Case the team worked on.
        team_id: Team that did the work.
        event: Closing event of the team, None when it stayed silent.
        message_count: Messages the orchestrator recorded for this team.
        state_count: Agents the orchestrator holds a state snapshot of.
        resumed: Whether the team was restored from the event store instead of
            created from scratch.
    """

    case_id: str
    team_id: uuid.UUID
    event: CaseClosed | None
    message_count: int
    state_count: int
    resumed: bool = False


class CaseRunner:
    """Owns the actor system and runs cases in a team of their own.

    Use as a context manager: leaving the block shuts the actor system down,
    which is the only part of this demo that must not be skipped.
    """

    def __init__(
        self,
        event_store_dir: Path,
        timeout_seconds: float = CASE_TIMEOUT_SECONDS,
        subscribers: Sequence[EventSubscriber] = (),
    ) -> None:
        """Start the actor system and the manager that owns the teams.

        Args:
            event_store_dir: Directory the event streams of the teams land in.
            timeout_seconds: How long a case may take before it is given up on.
            subscribers: Extra listeners to give to every team, for instance a
                tap on the messages. They are shared by all teams, so they must
                be thread safe and route on `team_id`.
        """
        self._timeout_seconds = timeout_seconds
        self.event_store_dir = event_store_dir

        # Filled by the subscriber on the actor thread of an orchestrator, read
        # on the thread that owns the lifecycle of the teams.
        self._closed: ClosedQueue = queue.Queue()

        self._actor_system = ActorSystem()
        self._event_store = YamlEventStore(event_store_dir)
        self._manager = TeamManager(
            actor_system=self._actor_system,
            event_store=self._event_store,
            # Shared by every team of this run, so they route on team_id.
            subscribers=[CaseClosedSubscriber(self._closed), *subscribers],
        )

    def __enter__(self) -> CaseRunner:
        """Return the runner itself, everything is already started."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Shut the actor system down, whatever happened inside the block."""
        self._actor_system.shutdown(timeout=SHUTDOWN_TIMEOUT_SECONDS)

    def run_case(self, case_id: str, requester_id: str) -> CaseRunResult:
        """Run one case in a team of its own, from request to closing event.

        A team needs no wiring at all: colleagues are looked up by name, the case
        store is built by `@CaseRepository` from the backend in its config, and
        the end of the case arrives here as a `CaseClosed` event.

        Args:
            case_id: Case to work on.
            requester_id: Human asking for the case to be handled.

        Returns:
            The outcome of the run, timed out or not.
        """
        runtime = self._manager.create_team(
            team_card=case_team_card(case_id=case_id),
            user_id=requester_id,
            metadata=CaseMetaData(case_id=case_id),
        )

        return self._work(runtime, case_id, requester_id, resumed=False)

    def resume_case(self, team_id: uuid.UUID, requester_id: str) -> CaseRunResult:
        """Rebuild a stopped team from the event store and give it its case again.

        `resume_team` recreates the agents from the `StartMessage`s in the stream,
        hands each of them its last state snapshot back and replays the history
        into the orchestrator. Replay reaches subscribers, not agents, so nothing
        the team did before happens a second time - the human is not asked the
        old questions again. It is a fresh `HandleCaseRequest` that puts the team
        back to work, and the coordinator starts its case over from `triaging`.

        Args:
            team_id: Team to resume.
            requester_id: Human asking for the case to be handled again.

        Returns:
            The outcome of the run, timed out or not.

        Raises:
            ValueError: If the team is unknown, still running, or deleted.
        """
        process = self._event_store.load_team(team_id)

        if process is None:
            raise ValueError(f"Team {team_id} is not in the event store")

        runtime = self._manager.resume_team(team_id)

        return self._work(runtime, case_id_of(process), requester_id, resumed=True)

    def list_teams(self, *, include_deleted: bool = False) -> list[Process]:
        """Every team the event store knows, oldest first.

        Args:
            include_deleted: Whether to keep the teams that were deleted.

        Returns:
            The stored teams, in the order they were created.
        """
        processes = self._event_store.list_teams()

        if not include_deleted:
            processes = [p for p in processes if p.status != TeamStatus.DELETED]

        return sorted(processes, key=lambda process: process.created_at)

    def load_team(self, team_id: uuid.UUID) -> Process | None:
        """Load one stored team.

        Args:
            team_id: Team to look up.

        Returns:
            The stored team, or None when the store does not know it.
        """
        return self._event_store.load_team(team_id)

    def load_events(self, team_id: uuid.UUID) -> list[PersistedEvent]:
        """Load the whole event stream of one team.

        Args:
            team_id: Team to read.

        Returns:
            Its events in sequence order, empty when there are none.
        """
        return self._event_store.load_events(team_id)

    def load_agent_states(self, team_id: uuid.UUID) -> list[AgentStateSnapshot]:
        """Load the last state snapshot of every agent of one team.

        Args:
            team_id: Team to read.

        Returns:
            One snapshot per agent, empty when there are none.
        """
        return self._event_store.load_agent_states(team_id)

    def _work(
        self,
        runtime: TeamRuntime,
        case_id: str,
        requester_id: str,
        *,
        resumed: bool,
    ) -> CaseRunResult:
        """Put a live team to work on its case and stop it afterwards.

        Args:
            runtime: The team, freshly created or resumed.
            case_id: Case the team works on.
            requester_id: Human asking for the case to be handled.
            resumed: Whether this team came out of the event store.

        Returns:
            The outcome of the run, timed out or not.
        """
        try:
            runtime.send(HandleCaseRequest(requester_id=requester_id))
            event = self._await_case(runtime.id)

            return CaseRunResult(
                case_id=case_id,
                team_id=runtime.id,
                event=event,
                message_count=len(runtime.orchestrator_proxy.get_messages()),
                state_count=len(runtime.orchestrator_proxy.get_states()),
                resumed=resumed,
            )
        finally:
            # Marks the Process STOPPED -> resumable, and waits for every mailbox
            # to drain: that barrier keeps the last output of this team out of the
            # next prompt, and stops two @UserProxy actors from competing for stdin.
            self._manager.stop_team(runtime.id)

    def _await_case(self, team_id: uuid.UUID) -> CaseClosed | None:
        """Wait until the team announces its case as closed.

        Filters on `team_id`: a team that timed out earlier may still deliver,
        and such a late event must not be read as the answer of the current team.

        Args:
            team_id: Team being waited for.

        Returns:
            The event, or None when the team stayed silent long enough.
        """
        deadline = time.monotonic() + self._timeout_seconds

        while (remaining := deadline - time.monotonic()) > 0:
            try:
                closed_team_id, event = self._closed.get(timeout=remaining)
            except queue.Empty:
                return None

            if closed_team_id == team_id:
                return event

        return None

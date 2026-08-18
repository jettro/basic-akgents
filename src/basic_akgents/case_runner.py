"""Running cases, one short-lived team per case.

Everything with a lifecycle lives here: the `ActorSystem`, the `TeamManager`
with its event store, and the subscriber that reports a case as closed. A team
is created for a single case and stopped again as soon as that case is done,
which is what teams in this framework are for.

`run_case` returns what happened, it never prints: the console layer decides how
to show a result, this layer only produces one.
"""

from __future__ import annotations

import queue
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from akgentic.core import ActorSystem, UserProxy
from akgentic.team import TeamManager, YamlEventStore

from basic_akgents.case_closed_subscriber import CaseClosedSubscriber, ClosedQueue
from basic_akgents.case_coordinator import HandleCaseRequest
from basic_akgents.case_events import CaseClosed
from basic_akgents.case_model import CaseMetaData
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
    """

    case_id: str
    team_id: uuid.UUID
    event: CaseClosed | None
    message_count: int
    state_count: int


class CaseRunner:
    """Owns the actor system and runs cases in a team of their own.

    Use as a context manager: leaving the block shuts the actor system down,
    which is the only part of this demo that must not be skipped.
    """

    def __init__(
        self,
        event_store_dir: Path,
        proxy_class: type[UserProxy],
        timeout_seconds: float = CASE_TIMEOUT_SECONDS,
    ) -> None:
        """Start the actor system and the manager that owns the teams.

        Args:
            event_store_dir: Directory the event streams of the teams land in.
            proxy_class: `UserProxy` subclass the teams talk to the human with.
            timeout_seconds: How long a case may take before it is given up on.
        """
        self._proxy_class = proxy_class
        self._timeout_seconds = timeout_seconds

        # Filled by the subscriber on the actor thread of an orchestrator, read
        # on the thread that owns the lifecycle of the teams.
        self._closed: ClosedQueue = queue.Queue()

        self._actor_system = ActorSystem()
        self._manager = TeamManager(
            actor_system=self._actor_system,
            event_store=YamlEventStore(event_store_dir),
            # Shared by every team of this run, so it routes on team_id.
            subscribers=[CaseClosedSubscriber(self._closed)],
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

        try:
            runtime.send(HandleCaseRequest(requester_id=requester_id))
            event = self._await_case(runtime.id)

            return CaseRunResult(
                case_id=case_id,
                team_id=runtime.id,
                event=event,
                message_count=len(runtime.orchestrator_proxy.get_messages()),
                state_count=len(runtime.orchestrator_proxy.get_states()),
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

"""Bridge between the case teams and the loop that drives the console."""

from __future__ import annotations

import queue
import uuid

from akgentic.core import EventSubscriber
from akgentic.core.messages import Message
from akgentic.core.messages.orchestrator import EventMessage

from basic_akgents.case_events import CaseClosed

# Every closed case, tagged with the team that closed it.
ClosedQueue = queue.Queue[tuple[uuid.UUID, CaseClosed]]


class CaseClosedSubscriber(EventSubscriber):
    """Hands every `CaseClosed` of every team to the thread driving the CLI.

    One instance is shared by all teams of a `TeamManager`, so it has to be
    thread safe - a `queue.Queue` is - and it must route on `team_id` instead
    of assuming a single team.

    It transports, it does not act: `on_message` runs on the actor thread of
    the orchestrator that published the event, and stopping that very team from
    here would deadlock. The owning thread decides what happens next.
    """

    def __init__(self, closed: ClosedQueue) -> None:
        """Store the queue the console loop reads.

        Args:
            closed: Queue every closed case is published on.
        """
        self._closed = closed
        self._restoring: set[uuid.UUID] = set()

    def on_message(self, msg: Message) -> None:
        """Forward a closed case, ignoring every other telemetry message.

        Args:
            msg: Telemetry message of one of the teams.
        """
        if not isinstance(msg, EventMessage) or not isinstance(msg.event, CaseClosed):
            return

        if msg.team_id is None or msg.team_id in self._restoring:
            # Untagged, or a replay of a case that was closed in an earlier run.
            return

        self._closed.put((msg.team_id, msg.event))

    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:
        """Keep replayed history out of the queue.

        Args:
            team_id: Team being restored.
            restoring: True while `resume_team` replays the event stream.
        """
        if restoring:
            self._restoring.add(team_id)
        else:
            self._restoring.discard(team_id)

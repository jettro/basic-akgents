"""A tap on the telemetry of every team, for whoever wants to watch it live.

`CaseClosedSubscriber` listens for one event type and ignores the rest; this one
keeps everything: every message the orchestrator of every team publishes, which
is the whole conversation plus the telemetry around it.

Like that subscriber it transports and does not act: `on_message` runs on the
actor thread of the orchestrator that published the message, so the only thing
that happens here is a put on a queue. Whoever drains that queue decides what
the messages are good for - printing them, counting them, writing them away.
"""

from __future__ import annotations

import queue
import uuid

from akgentic.core import EventSubscriber
from akgentic.core.messages import Message

# Every message of every team, tagged with the team that published it.
TappedQueue = queue.Queue[tuple[uuid.UUID | None, Message]]

# Room for a long case, and a hard ceiling: an actor thread must never block on
# a reader that fell behind, so a full queue drops instead of waiting.
TAP_CAPACITY = 5_000


class EventTap(EventSubscriber):
    """Puts every message of every team on a queue for a reader outside the team.

    One instance is shared by all teams of a `TeamManager`, so the team is
    tagged on every entry instead of assumed, and the queue - `queue.Queue` is
    thread safe - is the only thing touched from the actor threads.
    """

    def __init__(self, tapped: TappedQueue) -> None:
        """Store the queue every message is published on.

        Args:
            tapped: Queue the reader of the feed drains.
        """
        self._tapped = tapped
        self._restoring: set[uuid.UUID] = set()

        # Approximate on purpose: incremented from the actor thread of every
        # team, read by the console. A dropped event is worth reporting, an
        # exact count of them is not worth a lock on this path.
        self.dropped = 0

    def on_message(self, msg: Message) -> None:
        """Hand one message to the reader, or drop it when nobody keeps up.

        Args:
            msg: Message published by the orchestrator of one of the teams.
        """
        if msg.team_id is not None and msg.team_id in self._restoring:
            # Replay of a team being resumed: history, not something happening now.
            return

        try:
            self._tapped.put_nowait((msg.team_id, msg))
        except queue.Full:
            self.dropped += 1

    def set_restoring(self, team_id: uuid.UUID, restoring: bool) -> None:
        """Keep replayed history out of the live feed.

        Args:
            team_id: Team being restored.
            restoring: True while `resume_team` replays the event stream.
        """
        if restoring:
            self._restoring.add(team_id)
        else:
            self._restoring.discard(team_id)

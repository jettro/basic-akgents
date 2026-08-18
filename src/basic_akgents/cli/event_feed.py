"""The live feed of the tap: drain it, keep a tail of it, echo it when asked.

The teams publish on their own actor threads, the console prints on the main
thread, and neither may wait for the other. `EventTap` hands the messages over
on a queue, this class drains that queue on a thread of its own, and everything
it keeps is guarded by one lock.

One console cannot show a prompt and a stream at the same time. So there are
three ways to look at the feed, and the human picks: `feed` prints the tail
afterwards, `follow` echoes every message as it arrives (mixed in with the
questions of the team), and the log file is a panel of its own - `tail -f` it in
a second terminal and the stream never touches the prompt.
"""

from __future__ import annotations

import queue
import threading
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import IO

from akgentic.core.messages import Message

from basic_akgents.cli import console
from basic_akgents.cli.console import FeedLine
from basic_akgents.event_tap import TAP_CAPACITY, EventTap, TappedQueue

# Messages kept in memory for the `feed` command.
FEED_BUFFER = 500

# How long the drain thread waits for a message before it looks at the stop flag.
DRAIN_TIMEOUT_SECONDS = 0.2

# Grace period for the drain thread to notice that flag.
JOIN_TIMEOUT_SECONDS = 2.0


class EventFeed:
    """Everything the console does with the messages the tap collects.

    Attributes:
        tap: The subscriber to hand to `CaseRunner`, which gives it to the teams.
        log_path: File every captured message is appended to, None to write none.
    """

    def __init__(
        self,
        log_path: Path | None = None,
        *,
        following: bool = False,
        buffer_size: int = FEED_BUFFER,
    ) -> None:
        """Build the feed and the tap that fills it.

        Args:
            log_path: File to append every captured message to, for a `tail -f`
                in a second terminal. None writes no file.
            following: Whether to start out echoing every message immediately.
            buffer_size: Number of messages kept for the `feed` command.
        """
        self._tapped: TappedQueue = queue.Queue(maxsize=TAP_CAPACITY)
        self.tap = EventTap(self._tapped)
        self.log_path = log_path

        self._lines: deque[FeedLine] = deque(maxlen=buffer_size)
        self._lock = threading.Lock()
        self._following = following
        self._captured = 0

        self._log: IO[str] | None = None
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._drain, name="event-feed", daemon=True)

    def start(self) -> None:
        """Start draining the tap."""
        self._thread.start()

    def stop(self) -> None:
        """Stop draining and close the log file."""
        self._stopping.set()
        self._thread.join(timeout=JOIN_TIMEOUT_SECONDS)

        if self._log is not None:
            self._log.close()
            self._log = None

    @property
    def following(self) -> bool:
        """Whether every message is echoed as it arrives."""
        with self._lock:
            return self._following

    @property
    def captured(self) -> int:
        """How many messages were captured since the start."""
        with self._lock:
            return self._captured

    @property
    def dropped(self) -> int:
        """How many messages were dropped because the feed fell behind."""
        return self.tap.dropped

    def toggle_following(self) -> bool:
        """Switch the live echo on or off.

        Returns:
            Whether messages are echoed from now on.
        """
        with self._lock:
            self._following = not self._following
            return self._following

    def recent(self, limit: int) -> list[FeedLine]:
        """The last captured messages, oldest first.

        Args:
            limit: How many to return at most.

        Returns:
            The tail of the feed, as far as it is still in the buffer.
        """
        with self._lock:
            lines = list(self._lines)

        return lines[-limit:] if limit > 0 else lines

    def _drain(self) -> None:
        """Read the tap until the feed is stopped."""
        while not self._stopping.is_set():
            try:
                team_id, message = self._tapped.get(timeout=DRAIN_TIMEOUT_SECONDS)
            except queue.Empty:
                continue

            self._record(team_id, message)

    def _record(self, team_id: uuid.UUID | None, message: Message) -> None:
        """Render one message and hand it to every sink that wants it.

        Args:
            team_id: Team that published the message.
            message: The message itself.
        """
        line = FeedLine(
            team_id=team_id,
            at=datetime.now(UTC),
            text=console.render_event(message),
        )

        with self._lock:
            self._lines.append(line)
            self._captured += 1
            following = self._following

        self._append_to_log(line)

        if following:
            console.print_feed_line(line)

    def _append_to_log(self, line: FeedLine) -> None:
        """Append one rendered message to the log file, if there is one.

        Only the drain thread ever touches the handle, so it needs no lock.

        Args:
            line: The captured message.
        """
        if self.log_path is None:
            return

        if self._log is None:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log = self.log_path.open("a", encoding="utf-8")

        stamp = line.at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        self._log.write(f"{stamp} {str(line.team_id)[:8]} {line.text}\n")
        self._log.flush()

"""Human-in-the-loop bridge for the command line."""

from __future__ import annotations

import threading

from akgentic.core import ActorAddress, BaseState, UserProxy
from akgentic.core.messages import ResultMessage, UserMessage


def _name_of(address: ActorAddress | None) -> str:
    """Return a printable name for an actor address."""
    return getattr(address, "name", None) or "team"


class CliUserProxyAgent(UserProxy):
    """UserProxy that asks the human on stdin and prints the final answer.

    The agent thread blocks while `input()` waits, which is fine for a console
    demo: messages arriving meanwhile simply queue up in the mailbox.
    """

    def on_start(self) -> None:
        """Initialize the user proxy."""
        self.state = BaseState()
        self.state.observer(self)

        # Signalled once the team reports the case as handled, so the caller
        # (main) knows when it may shut the actor system down.
        self.completed: threading.Event | None = None

    def set_completion_event(self, completed: threading.Event) -> None:
        """Set the event to signal when the case has been handled.

        Args:
            completed: Event the caller waits on instead of sleeping.
        """
        self.completed = completed

    def receiveMsg_UserMessage(self, message: UserMessage, sender: ActorAddress) -> None:  # noqa: N802
        """Ask the human a question and route the answer back to the asker."""
        print(f"\n[{_name_of(sender)}] {message.content}")
        try:
            answer = input("> ").strip()
        except EOFError:
            answer = ""

        self.process_human_input(answer, message)

    def receiveMsg_ResultMessage(self, message: ResultMessage, sender: ActorAddress) -> None:  # noqa: N802
        """Show the final answer of the team and release the caller."""
        print(f"\n[{_name_of(sender)}] {message.content}")

        if self.completed is not None:
            self.completed.set()

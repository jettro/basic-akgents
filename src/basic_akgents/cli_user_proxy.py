"""Human-in-the-loop bridge for the command line."""

from __future__ import annotations

from akgentic.core import ActorAddress, BaseState, UserProxy
from akgentic.core.messages import ResultMessage, UserMessage

from basic_akgents.terminal import ask, say


def _name_of(address: ActorAddress | None) -> str:
    """Return a printable name for an actor address."""
    return getattr(address, "name", None) or "team"


class CliUserProxyAgent(UserProxy):
    """UserProxy that asks the human on stdin and prints the final answer.

    The agent thread blocks while `input()` waits, which is fine for a console
    demo: messages arriving meanwhile simply queue up in the mailbox.

    Printing is all this agent does. That the case is finished is announced by
    the coordinator as a `CaseClosed` event, which the console loop picks up
    through its subscriber - so nothing has to be handed to this agent.

    It prints through `basic_akgents.terminal`, the same `rich` console the front
    end uses, so a question and a report look the same wherever they come from.
    """

    def on_start(self) -> None:
        """Initialize the user proxy."""
        self.state = BaseState()
        self.state.observer(self)

    def receiveMsg_UserMessage(self, message: UserMessage, sender: ActorAddress) -> None:
        """Ask the human a question and route the answer back to the asker."""
        say(_name_of(sender), message.content, style="msg.domain")
        try:
            answer = ask().strip()
        except EOFError:
            answer = ""

        self.process_human_input(answer, message)

    def receiveMsg_ResultMessage(self, message: ResultMessage, sender: ActorAddress) -> None:
        """Show the final answer of the team."""
        say(_name_of(sender), message.content, style="msg.result")

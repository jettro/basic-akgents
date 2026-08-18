from functools import cached_property

from akgentic.core import ActorAddress, Akgent, BaseState
from akgentic.core.messages import Message, ResultMessage, UserMessage

from basic_akgents.case_events import CaseClosed
from basic_akgents.case_model import CaseConfig
from basic_akgents.case_priority import PRIORITY_SCALE, TRIAGE_PRIORITIES, CasePriority
from basic_akgents.case_team import CASE_TRIAGE, USER_PROXY, find_team_member
from basic_akgents.case_triage import (
    CasePriorityDecision,
    CaseTriageCompleted,
    CaseTriageRequest,
    CaseTriageResponse,
)

# Answers of the human that approve the proposal of triage, empty means "yes".
APPROVALS = ("", "y", "yes", "ok", "approve", "approved")


class HandleCaseRequest(Message):
    requester_id:str = ""

class CaseCoordinatorState(BaseState):
    status: str = "new"
    requester_id: str = ""
    case_description: str = ""
    proposed_priority: CasePriority = CasePriority.UNSET

class CaseCoordinatorConfig(CaseConfig):
    pass

class CaseCoordinatorAgent(Akgent[CaseCoordinatorConfig, CaseCoordinatorState]):
    """Runs the case from request to answer, without owning any of the work.

    Colleagues are not handed to this agent, it looks them up by name on the
    first message that needs them - never in `on_start`, where the children of
    the team do not exist yet.
    """

    def on_start(self) -> None:
        """Initialize the case coordinator."""
        self.state = CaseCoordinatorState() # Initialize the first state object
        self.state.observer(self)

    @cached_property
    def triage_agent(self) -> ActorAddress:
        """Address of triage, resolved on the first case and kept afterwards."""
        return find_team_member(self, CASE_TRIAGE)

    @cached_property
    def user_proxy(self) -> ActorAddress:
        """Address of the human bridge, resolved on the first question."""
        return find_team_member(self, USER_PROXY)

    def receiveMsg_HandleCaseRequest(self, message: HandleCaseRequest, sender: ActorAddress) -> None:
        """Start the case by having it triaged, everything we need is in the case."""
        self.update_state({"status": "triaging", "requester_id": message.requester_id})
        self.send(self.triage_agent, CaseTriageRequest(requester_id=message.requester_id))

    def receiveMsg_CaseTriageResponse(self, message: CaseTriageResponse, sender: ActorAddress) -> None:
        """Put the proposed priority in front of the human for approval."""
        if not message.known_case:
            self.update_state({"status": "unknown"})
            self._close(
                f"Case {self.config.case_id} closed - {message.reason}",
                outcome="unknown",
                case_priority=CasePriority.UNSET,
            )
            return

        if message.already_prioritised:
            # Nothing to approve: only cases without a priority are triaged.
            self.update_state({
                "status": "already_prioritised",
                "case_description": message.case_description,
                "proposed_priority": message.case_priority,
            })
            self._close(
                f"Case {self.config.case_id} was not triaged - {message.reason}.\n"
                f"  description : {message.case_description}\n"
                f"  priority    : {message.case_priority.label}",
                outcome="already_prioritised",
                case_priority=message.case_priority,
            )
            return

        self.update_state({
            "status": "awaiting_approval",
            "case_description": message.case_description,
            "proposed_priority": message.case_priority,
        })

        self._ask(
            f"Case {self.config.case_id}\n"
            f"  description : {message.case_description}\n"
            f"  reported by : {message.case_sender}\n"
            f"  proposal    : priority {message.case_priority.label}, "
            f"because {message.reason}\n"
            f"  scale       : {PRIORITY_SCALE}\n"
            f"Approve priority {message.case_priority.label}? "
            f"[Enter/y] approve, [n] reject, or type another number (1-4)"
        )

    def receiveMsg_ResultMessage(self, message: ResultMessage, sender: ActorAddress) -> None:
        """Take the verdict of the human and let triage record it."""
        if self.state.status != "awaiting_approval":
            # No question is pending, so this answer is not ours to interpret.
            return

        approved, case_priority = self._read_decision(message.content)

        self.update_state({"status": "deciding", "proposed_priority": case_priority})

        self.send(
            self.triage_agent,
            CasePriorityDecision(
                approved=approved,
                case_priority=case_priority,
                decided_by=self.state.requester_id or "unknown",
            ),
        )

    def receiveMsg_CaseTriageCompleted(self, message: CaseTriageCompleted, sender: ActorAddress) -> None:
        """Report the recorded outcome of the triage back to the human."""
        if message.approved:
            self.update_state({"status": "handled"})
            self._close(
                f"Case {self.config.case_id} has been triaged.\n"
                f"  description : {message.case_description}\n"
                f"  priority    : {message.case_priority.label} (approved by "
                f"{self.state.requester_id or 'unknown'})",
                outcome="handled",
                case_priority=message.case_priority,
            )
            return

        self.update_state({"status": "rejected"})
        self._close(
            f"Case {self.config.case_id} - the proposed priority was rejected, "
            f"the case keeps priority {message.case_priority.label}.",
            outcome="rejected",
            case_priority=message.case_priority,
        )

    def _read_decision(self, answer: str) -> tuple[bool, CasePriority]:
        """Interpret what the human typed about the proposed priority.

        Args:
            answer: Raw text the human entered.

        Returns:
            Whether the priority is approved and the priority to record. A
            valid priority number approves that number instead of the
            proposal, anything else counts as a rejection.
        """
        cleaned = answer.strip().lower()

        if cleaned in APPROVALS:
            return True, self.state.proposed_priority

        if cleaned.isdigit() and int(cleaned) in TRIAGE_PRIORITIES:
            return True, CasePriority(int(cleaned))

        return False, self.state.proposed_priority

    def _ask(self, content: str) -> None:
        """Ask the human a question through the user proxy.

        Args:
            content: Question shown to the human.
        """
        self.send(self.user_proxy, UserMessage(content=content))

    def _close(self, content: str, outcome: str, case_priority: CasePriority) -> None:
        """Report the outcome to the human and announce the case as closed.

        The report is a message to the human bridge, the event is telemetry: it
        reaches every subscriber of the team and is persisted, so anything
        outside the team - the console loop, a UI, an audit log - can react to a
        finished case without knowing this agent.

        Args:
            content: Text shown to the human, closing the request.
            outcome: Final status, mirroring `state.status`.
            case_priority: Priority the case is left with.
        """
        self.send(self.user_proxy, ResultMessage(content=content))
        self.notify_event(
            CaseClosed(
                case_id=self.config.case_id,
                outcome=outcome,
                case_priority=case_priority,
            )
        )

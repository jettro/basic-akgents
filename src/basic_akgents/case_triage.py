from functools import cached_property

from akgentic.core import ActorAddress, Akgent, BaseState
from akgentic.core.agent import WarningError
from akgentic.core.messages import Message

from basic_akgents.case_model import CaseConfig
from basic_akgents.case_priority import CasePriority
from basic_akgents.case_repository_agent import (
    CaseInformationRequest,
    CaseInformationResponse,
    CaseUpdateRequest,
    CaseUpdateResponse,
)
from basic_akgents.case_team import CASE_REPOSITORY, find_team_member

URGENT_WORDS = ("urgent", "asap", "immediately", "outage")

# Priority assigned when nothing urgent is found in the case.
DEFAULT_PRIORITY = CasePriority.NORMAL
URGENT_PRIORITY = CasePriority.CRITICAL


class CaseTriageRequest(Message):
    """Ask triage to assess the case it was configured with."""

    requester_id: str = ""


class CaseTriageResponse(Message):
    """Proposal of triage, nothing is stored yet - the human decides."""

    case_description: str = ""
    case_sender: str = ""
    case_priority: CasePriority = CasePriority.UNSET
    reason: str = ""
    known_case: bool = False
    already_prioritised: bool = False


class CasePriorityDecision(Message):
    """Verdict of the human on the proposed priority."""

    approved: bool = False
    case_priority: CasePriority = CasePriority.UNSET
    decided_by: str = ""


class CaseTriageCompleted(Message):
    """Triage is done, the decision has been written to the case system."""

    case_description: str = ""
    case_priority: CasePriority = CasePriority.UNSET
    approved: bool = False


class CaseTriageConfig(CaseConfig):
    pass


class CaseTriageState(BaseState):
    known_case: bool = False
    proposed_priority: CasePriority = CasePriority.UNSET
    requester_id: str = ""
    approved: bool = False
    status: str = "new"


class CaseTriageAgent(Akgent[CaseTriageConfig, CaseTriageState]):
    """Assesses one case, but never touches the case store itself.

    Case data lives behind `@CaseRepository`, so every step that needs it is a
    request now and the answer arrives as a message. Triage therefore waits in
    its *state* (`status`) instead of in a blocked thread:

        CaseTriageRequest    -> CaseInformationRequest  -> CaseTriageResponse
        CasePriorityDecision -> CaseUpdateRequest       -> CaseTriageCompleted
    """

    # Whoever asked for this piece of work, never state: an address is not
    # serializable.
    reply_to: ActorAddress | None

    def on_start(self) -> None:
        self.state = CaseTriageState()
        self.reply_to = None
        self.state.observer(self)

    @cached_property
    def repository_agent(self) -> ActorAddress:
        """Address of the case store owner, resolved on the first request."""
        return find_team_member(self, CASE_REPOSITORY)

    def receiveMsg_CaseTriageRequest(
        self, message: CaseTriageRequest, sender: ActorAddress
    ) -> None:
        """Ask the repository for the case; the assessment follows on its answer."""
        self.reply_to = sender

        print("CaseTriageRequest received")

        self.update_state(
            {
                "status": "loading",
                "requester_id": message.requester_id or "unknown",
            }
        )

        self.send(self.repository_agent, CaseInformationRequest(case_id=self.config.case_id))

    def receiveMsg_CaseInformationResponse(
        self, message: CaseInformationResponse, sender: ActorAddress
    ) -> None:
        """Assess the case and propose a priority, without storing it yet."""
        if self.state.status != "loading":
            # No request of ours is open, so this answer is not ours to act on.
            return

        case = message.case

        if not message.found or case is None:
            self.update_state({"status": "unknown_case", "known_case": False})
            self._reply(
                CaseTriageResponse(
                    case_sender=self.state.requester_id,
                    known_case=False,
                    reason=f"Case {self.config.case_id} is not known in the case system.",
                )
            )
            return

        # Only new cases are triaged: a priority that is already there was
        # decided on before and is not ours to overwrite.
        if case.case_priority.is_set:
            self.update_state(
                {
                    "status": "already_prioritised",
                    "known_case": True,
                    "proposed_priority": case.case_priority,
                }
            )
            self._reply(
                CaseTriageResponse(
                    case_description=case.case_description,
                    case_sender=self.state.requester_id,
                    case_priority=case.case_priority,
                    reason=f"the case already has priority {case.case_priority.label}",
                    known_case=True,
                    already_prioritised=True,
                )
            )
            return

        # Everything triage needs is in the case itself.
        case_priority, reason = self._assess(case.case_description)

        self.update_state(
            {"status": "proposed", "known_case": True, "proposed_priority": case_priority}
        )

        self._reply(
            CaseTriageResponse(
                case_description=case.case_description,
                case_sender=self.state.requester_id,
                case_priority=case_priority,
                reason=reason,
                known_case=True,
            )
        )

    def receiveMsg_CasePriorityDecision(
        self, message: CasePriorityDecision, sender: ActorAddress
    ) -> None:
        """Hand the decision of the human to the agent that owns the case."""
        self.reply_to = sender

        decided_by = message.decided_by or "unknown"

        if message.approved:
            case_priority = message.case_priority
            action = f"priority {case_priority.label} approved by {decided_by}"
        else:
            # Rejected: the case keeps the priority it already had, only the
            # refusal is logged so the next handler can see it. UNSET tells the
            # repository to leave the stored priority alone.
            case_priority = CasePriority.UNSET
            action = (
                f"proposed priority {self.state.proposed_priority.label} rejected by {decided_by}"
            )

        self.update_state({"status": "storing", "approved": message.approved})

        self.send(
            self.repository_agent,
            CaseUpdateRequest(
                case_id=self.config.case_id,
                case_priority=case_priority,
                action=action,
            ),
        )

    def receiveMsg_CaseUpdateResponse(
        self, message: CaseUpdateResponse, sender: ActorAddress
    ) -> None:
        """Report the stored outcome once the repository wrote the decision."""
        if self.state.status != "storing":
            return

        case = message.case

        if not message.found or case is None:
            raise WarningError(
                f"Case {self.config.case_id} disappeared before the decision was stored."
            )

        approved = self.state.approved

        self.update_state({"status": "completed" if approved else "rejected"})

        self._reply(
            CaseTriageCompleted(
                case_description=case.case_description,
                case_priority=case.case_priority,
                approved=approved,
            )
        )

    def _reply(self, message: Message) -> None:
        """Answer whoever asked triage for this piece of work.

        Args:
            message: Answer for the requester.
        """
        if self.reply_to is not None:
            self.send(self.reply_to, message)

    @staticmethod
    def _assess(case_description: str) -> tuple[CasePriority, str]:
        """Derive a priority from the case description.

        Args:
            case_description: Text of the case as stored in the case system.

        Returns:
            The proposed priority and the reason behind it.
        """
        text = case_description.lower()
        hit = next((word for word in URGENT_WORDS if word in text), None)

        if hit is not None:
            return URGENT_PRIORITY, f"the case mentions '{hit}'"

        return DEFAULT_PRIORITY, "no urgency signals in the case description"

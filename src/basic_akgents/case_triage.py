from akgentic.core import Akgent, BaseState, ActorAddress
from akgentic.core.agent import WarningError
from akgentic.core.messages import Message

from basic_akgents.case_model import CaseConfig
from basic_akgents.case_priority import CasePriority
from basic_akgents.case_repository import Case, CaseNotFoundError, CaseRepository

URGENT_WORDS = ("urgent", "asap", "immediately", "outage")

# Priority assigned when nothing urgent is found in the case.
DEFAULT_PRIORITY = CasePriority.NORMAL
URGENT_PRIORITY = CasePriority.CRITICAL

class CaseTriageRequest(Message):
    """Ask triage to assess the case it was configured with."""
    requester_id:str = ""

class CaseTriageResponse(Message):
    """Proposal of triage, nothing is stored yet - the human decides."""
    case_description:str = ""
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
    status: str = "new"

class CaseTriageAgent(Akgent[CaseTriageConfig, CaseTriageState]):
    # Live collaborators, never state: they are not serializable.
    cases: CaseRepository | None

    def on_start(self) -> None:
        self.state = CaseTriageState()

        self.cases = None

        self.state.observer(self)

    def set_case_repository(self, repository: CaseRepository) -> None:
        """Inject the case backend this agent works with.

        Args:
            repository: Any object implementing `CaseRepository`.
        """
        self.cases = repository

    def receiveMsg_CaseTriageRequest(self, message: CaseTriageRequest, sender: ActorAddress) -> None:
        """Assess the case and propose a priority, without storing it yet."""
        case = self._load_case()

        if case is None:
            self.update_state({"status": "unknown_case", "known_case": False})
            self.send(
                sender,
                CaseTriageResponse(
                    case_sender=message.requester_id or "unknown",
                    known_case=False,
                    reason=f"Case {self.config.case_id} is not known in the case system.",
                ),
            )
            return

        # Only new cases are triaged: a priority that is already there was
        # decided on before and is not ours to overwrite.
        if case.case_priority.is_set:
            self.update_state({"status": "already_prioritised", "known_case": True,
                               "proposed_priority": case.case_priority})
            self.send(
                sender,
                CaseTriageResponse(
                    case_description=case.case_description,
                    case_sender=message.requester_id or "unknown",
                    case_priority=case.case_priority,
                    reason=f"the case already has priority {case.case_priority.label}",
                    known_case=True,
                    already_prioritised=True,
                ),
            )
            return

        # Everything triage needs is in the case itself.
        case_priority, reason = self._assess(case.case_description)

        self.update_state(
            {"status": "proposed", "known_case": True, "proposed_priority": case_priority}
        )

        self.send(
            sender,
            CaseTriageResponse(
                case_description=case.case_description,
                case_sender=message.requester_id or "unknown",
                case_priority=case_priority,
                reason=reason,
                known_case=True,
            ),
        )

    def receiveMsg_CasePriorityDecision(self, message: CasePriorityDecision, sender: ActorAddress) -> None:
        """Write the decision of the human to the case system."""
        case = self._load_case()

        if case is None:
            raise WarningError(f"Case {self.config.case_id} disappeared before the decision was stored.")

        decided_by = message.decided_by or "unknown"

        if message.approved:
            case_priority = message.case_priority
            action = f"priority {case_priority.label} approved by {decided_by}"
        else:
            # Rejected: the case keeps the priority it already had, only the
            # refusal is logged so the next handler can see it.
            case_priority = case.case_priority
            action = (
                f"proposed priority {self.state.proposed_priority.label} "
                f"rejected by {decided_by}"
            )

        # Frozen fields stay as they are, the triage result is written back.
        case = case.model_copy(
            update={
                "case_priority": case_priority,
                "actions": [*case.actions, action],
            }
        )
        self.cases.save_case(case)

        self.update_state({"status": "completed" if message.approved else "rejected"})

        self.send(
            sender,
            CaseTriageCompleted(
                case_description=case.case_description,
                case_priority=case.case_priority,
                approved=message.approved,
            ),
        )

    def _load_case(self) -> Case | None:
        """Load the configured case.

        Returns:
            The stored case, or None when the case system does not know it.
        """
        if self.cases is None:
            raise WarningError("No case repository available, call set_case_repository first.")

        try:
            return self.cases.load_case(self.config.case_id)
        except CaseNotFoundError:
            return None

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

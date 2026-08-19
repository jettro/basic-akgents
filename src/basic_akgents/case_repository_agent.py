"""The agent that owns the case store: all case data goes in and out by message."""

from __future__ import annotations

from functools import cached_property
from typing import Any

from akgentic.core import ActorAddress, Akgent, BaseState, BaseConfig
from akgentic.core.messages import Message

from basic_akgents.case_priority import CasePriority
from basic_akgents.case_repository import (
    DEFAULT_CASE_REPOSITORY,
    Case,
    CaseNotFoundError,
    CaseRepository,
    build_case_repository,
)
from basic_akgents.case_team import find_team_case_id


class CaseInformationRequest(Message):
    """Ask the repository agent for everything known about the team case."""


class CaseInformationResponse(Message):
    """The team case as it is stored right now.

    Attributes:
        found: Whether the case system knows this case at all.
        case: The stored case, None when it is unknown.
    """

    found: bool = False
    case: Case | None = None


class CaseUpdateRequest(Message):
    """Ask the repository agent to record a decision on the team case.

    The agent reads, changes and writes the case in one handler, so an update
    can never overwrite one that another agent made in between.

    Attributes:
        case_priority: Priority to store, `UNSET` leaves the current one alone.
        action: Line to append to the audit log, empty appends nothing.
    """

    case_priority: CasePriority = CasePriority.UNSET
    action: str = ""


class CaseUpdateResponse(Message):
    """The team case as it is stored after the update.

    Attributes:
        found: Whether the case system knows this case at all.
        case: The stored case after the write, None when it is unknown.
    """

    found: bool = False
    case: Case | None = None


class CaseRepositoryConfig(BaseConfig):
    """Config of the case store owner.

    Attributes:
        backend: Dotted path of the `CaseRepository` implementation to use.
    """

    backend: str = DEFAULT_CASE_REPOSITORY


class CaseRepositoryState(BaseState):
    """Traffic to the store, so the telemetry shows who reads and writes."""

    reads: int = 0
    writes: int = 0
    last_case_id: str = ""
    status: str = "ready"


class CaseRepositoryAgent(Akgent[CaseRepositoryConfig, CaseRepositoryState]):
    """Single owner of the case store.

    Only this agent holds a `CaseRepository`, and its handlers run one at a time
    in its own thread. That gives the team two things the shared instance could
    not: read-modify-write is atomic without a lock, and every read and write
    shows up in the telemetry of the orchestrator.
    """

    # Live collaborator, never state: it is not serializable.
    cases: CaseRepository

    @cached_property
    def team_case_id(self) -> str:
        """Look up the case ID of the team."""
        return find_team_case_id(self)


    def on_start(self) -> None:
        self.state = CaseRepositoryState()

        self.cases = build_case_repository(self.config.backend)

        self.state.observer(self)

    def receiveMsg_CaseInformationRequest(
        self, message: CaseInformationRequest, sender: ActorAddress
    ) -> None:
        """Answer with the case as it is stored."""
        case = self._load(self.team_case_id)

        self.update_state(
            {
                "reads": self.state.reads + 1,
                "last_case_id": self.team_case_id,
                "status": "ready" if case is not None else "unknown_case",
            }
        )

        self.send(
            sender,
            CaseInformationResponse(case_id=self.team_case_id, found=case is not None, case=case),
        )

    def receiveMsg_CaseUpdateRequest(
        self, message: CaseUpdateRequest, sender: ActorAddress
    ) -> None:
        """Apply a decision to the case and answer with the stored result."""
        case = self._load(self.team_case_id)

        if case is not None:
            case = self._apply(case, message)

        self.update_state(
            {
                "writes": self.state.writes + 1,
                "last_case_id": self.team_case_id,
                "status": "ready" if case is not None else "unknown_case",
            }
        )

        self.send(
            sender,
            CaseUpdateResponse(found=case is not None, case=case),
        )

    def _apply(self, case: Case, message: CaseUpdateRequest) -> Case:
        """Write the requested change to the store.

        Args:
            case: The case as it was just loaded.
            message: The change to record.

        Returns:
            The case as it is stored after the update.
        """
        updates: dict[str, Any] = {}

        if message.case_priority.is_set:
            updates["case_priority"] = message.case_priority

        if message.action:
            updates["actions"] = [*case.actions, message.action]

        if not updates:
            return case

        # Frozen fields stay as they are, only the decision is written back.
        case = case.model_copy(update=updates)
        self.cases.save_case(case)

        return case

    def _load(self, case_id: str) -> Case | None:
        """Load a case from the store.

        Args:
            case_id: Identifier of the case to load.

        Returns:
            The stored case, or None when the case system does not know it.
        """
        try:
            return self.cases.load_case(case_id)
        except CaseNotFoundError:
            return None

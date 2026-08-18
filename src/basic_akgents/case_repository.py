"""Access to case data, kept behind an interface so agents stay backend-agnostic."""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from typing import Protocol, runtime_checkable

from akgentic.core.utils import import_class
from pydantic import BaseModel, Field

from basic_akgents.case_priority import CasePriority


class Case(BaseModel):
    """A single case as stored in the case system.

    Attributes:
        case_id: Identifier of the case, fixed for its lifetime.
        case_description: What the requester asked for, fixed once recorded.
        case_priority: Priority of the case, `UNSET` until triage decided one.
        actions: Log of what the team did with the case.
    """

    case_id: str = Field(frozen=True)
    case_description: str = Field(default="", frozen=True)
    case_priority: CasePriority = CasePriority.UNSET
    actions: list[str] = Field(default_factory=list)


class CaseNotFoundError(LookupError):
    """Raised when a case id is unknown to the repository."""


# A dotted path, exactly like AgentCard.agent_class: serializable, so it travels
# in the team card and survives a resume.
DEFAULT_CASE_REPOSITORY = "basic_akgents.case_repository.DummyCaseRepository"

@cache
def build_case_repository(backend: str = DEFAULT_CASE_REPOSITORY) -> CaseRepository:
    """Create the case backend named by a dotted path.

    One instance per backend path: the in-memory store must not be re-seeded
    when a team is resumed, and a database client should be pooled, not
    duplicated per agent.

    Args:
        backend: Fully qualified path of a `CaseRepository` implementation.

    Returns:
        The backend to work with.

    Raises:
        TypeError: If the resolved class is not a `CaseRepository`.
    """
    repository = import_class(backend)()

    if not isinstance(repository, CaseRepository):
        raise TypeError(f"{backend!r} does not implement CaseRepository")

    return repository


@runtime_checkable
class CaseRepository(Protocol):
    """Interface to a case backend.

    Structural typing: an implementation does not inherit from this class, it
    only has to provide the same methods. Every method is abstract on purpose -
    a Protocol with a real body would silently become a default implementation.
    """

    def load_case(self, case_id: str) -> Case:
        """Load a single case.

        Args:
            case_id: Identifier of the case to load.

        Returns:
            The stored case.

        Raises:
            CaseNotFoundError: If no case exists for this id.
        """
        ...

    def save_case(self, case: Case) -> None:
        """Store a case, overwriting an earlier version.

        Args:
            case: The case to persist.
        """
        ...


# A mix on purpose: the first three still have to be triaged, the last two were
# prioritised already and must be left alone.
DEMO_CASES: tuple[Case, ...] = (
    Case(
        case_id="case_1",
        case_description="The printer on the second floor jams on every duplex job",
    ),
    Case(
        case_id="case_2",
        case_description="Mail server is down for the whole department, urgent",
    ),
    Case(
        case_id="case_3",
        case_description="New colleague starts on Monday and needs a mail account",
    ),
    Case(
        case_id="case_4",
        case_description="Laptop was stolen from a car and has to be wiped",
        case_priority=CasePriority.CRITICAL,
        actions=["priority 1 approved by security"],
    ),
    Case(
        case_id="case_5",
        case_description="Request for a second monitor for the finance team",
        case_priority=CasePriority.LOW,
        actions=["priority 4 approved by servicedesk"],
    ),
)


class DummyCaseRepository:
    """In-memory `CaseRepository`, seeded with a few demo cases.

    Exactly one agent owns this store: `CaseRepositoryAgent` holds it and its
    handlers run one at a time in that agent's own thread, so no lock is needed.
    Hand it to a second agent and that guarantee is gone - then the
    implementation has to be thread safe again.

    Copies go in and out (`model_copy(deep=True)`), so a caller can never mutate
    what is stored by accident.
    """

    def __init__(self, cases: Iterable[Case] | None = None) -> None:
        """Initialize the repository.

        Args:
            cases: Cases to start with, defaults to `DEMO_CASES`.
        """
        self._cases: dict[str, Case] = {
            case.case_id: case.model_copy(deep=True)
            for case in (DEMO_CASES if cases is None else cases)
        }

    def load_case(self, case_id: str) -> Case:
        """Load a single case.

        Args:
            case_id: Identifier of the case to load.

        Returns:
            A copy of the stored case.

        Raises:
            CaseNotFoundError: If no case exists for this id.
        """
        case = self._cases.get(case_id)

        if case is None:
            raise CaseNotFoundError(f"No case found for id {case_id!r}")

        return case.model_copy(deep=True)

    def save_case(self, case: Case) -> None:
        """Store a case, overwriting an earlier version.

        Args:
            case: The case to persist.
        """
        self._cases[case.case_id] = case.model_copy(deep=True)

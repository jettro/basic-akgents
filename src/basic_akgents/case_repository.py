"""Access to case data, kept behind an interface so agents stay backend-agnostic."""

from __future__ import annotations

import threading
from collections.abc import Iterable
from functools import cache
from typing import Protocol, runtime_checkable

from akgentic.core.utils import import_class
from akgentic.core.utils.serializer import SerializableBaseModel
from pydantic import Field

from basic_akgents.case_priority import CasePriority


class Case(SerializableBaseModel):
    """A single case as stored in the case system.

    A `SerializableBaseModel` and not a plain `BaseModel`, because a case travels
    inside a message (`CaseInformationResponse`) and every message is persisted.
    The framework's serializer walks such a model field by field - which turns
    the `CasePriority` into the plain number the event store can read back - and
    writes the class path, so replay hands the agent a real `Case` again. A plain
    `BaseModel` is dumped by pydantic itself, keeps the enum object, and makes
    the YAML stream of the team unreadable: `resume` then finds no history.

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
def _case_repository(backend: str) -> CaseRepository:
    """Build the backend named by a dotted path, once per path.

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


def build_case_repository(backend: str = DEFAULT_CASE_REPOSITORY) -> CaseRepository:
    """Create the case backend named by a dotted path.

    One instance per backend path: the in-memory store must not be re-seeded
    when a team is resumed, and a database client should be pooled, not
    duplicated per agent.

    The cache sits on the private function that has no default, because `@cache`
    keys on the call and not on the resolved arguments: with the cache out here,
    `build_case_repository()` from the console and
    `build_case_repository(DEFAULT_CASE_REPOSITORY)` from `@CaseRepository` would
    be two keys - and two stores, so the console would show priorities that the
    team never wrote.

    Args:
        backend: Fully qualified path of a `CaseRepository` implementation.

    Returns:
        The backend to work with.

    Raises:
        TypeError: If the resolved class is not a `CaseRepository`.
    """
    return _case_repository(backend)


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

    def list_cases(self) -> list[Case]:
        """List every case the backend holds.

        Returns:
            All stored cases, ordered by case id.
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

    Exactly one agent *writes* this store: `CaseRepositoryAgent` holds it and its
    handlers run one at a time in that agent's own thread, so read-modify-write
    is atomic without help. The console reads the same instance to list the cases
    while a team may still be running, and that second thread is why every
    access takes a lock.

    Copies go in and out (`model_copy(deep=True)`), so a caller can never mutate
    what is stored by accident.
    """

    def __init__(self, cases: Iterable[Case] | None = None) -> None:
        """Initialize the repository.

        Args:
            cases: Cases to start with, defaults to `DEMO_CASES`.
        """
        self._lock = threading.Lock()
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
        with self._lock:
            case = self._cases.get(case_id)

        if case is None:
            raise CaseNotFoundError(f"No case found for id {case_id!r}")

        return case.model_copy(deep=True)

    def save_case(self, case: Case) -> None:
        """Store a case, overwriting an earlier version.

        Args:
            case: The case to persist.
        """
        with self._lock:
            self._cases[case.case_id] = case.model_copy(deep=True)

    def list_cases(self) -> list[Case]:
        """List every case the store holds.

        Returns:
            Copies of all stored cases, ordered by case id.
        """
        with self._lock:
            cases = list(self._cases.values())

        return [case.model_copy(deep=True) for case in sorted(cases, key=lambda c: c.case_id)]

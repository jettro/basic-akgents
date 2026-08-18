"""Domain events a case team publishes to whoever is listening.

A frozen dataclass, like the framework's own `ClosedNotification`: the
serializer writes the import path of this class into every persisted event and
replay resolves that string back - so moving or renaming it breaks the replay
of cases that were closed before.
"""

from __future__ import annotations

from dataclasses import dataclass

from basic_akgents.case_priority import CasePriority


@dataclass(frozen=True)
class CaseClosed:
    """The team is done with a case, whatever the outcome.

    Attributes:
        case_id: Case the team was created for.
        outcome: Final status of the coordinator, e.g. `handled`, `rejected`,
            `already_prioritised` or `unknown`.
        case_priority: Priority the case is left with.
    """

    case_id: str
    outcome: str
    case_priority: CasePriority = CasePriority.UNSET

"""The priority scale of a case.

A bare number is ambiguous - "is 4 higher than 3?" has no answer without a
legend. The scale is therefore named here once: lower is more urgent, and
everything a human reads shows the name next to the number.
"""

from __future__ import annotations

from enum import IntEnum


class CasePriority(IntEnum):
    """Priority of a case, `UNSET` means triage has not looked at it yet.

    An `IntEnum` so it keeps comparing and sorting like the plain integer it
    replaces (`CasePriority.CRITICAL < CasePriority.LOW`) and serializes as a
    number, while the member name carries the meaning.
    """

    UNSET = 0
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4

    @property
    def is_set(self) -> bool:
        """Whether a priority was assigned to the case."""
        return self is not CasePriority.UNSET

    @property
    def label(self) -> str:
        """Number and name together, e.g. `3 - normal`."""
        if self is CasePriority.UNSET:
            return "0 - not set"

        return f"{self.value} - {self.name.lower()}"


# Everything triage may propose or a human may pick: UNSET is not a choice.
TRIAGE_PRIORITIES: tuple[CasePriority, ...] = tuple(
    priority for priority in CasePriority if priority.is_set
)

# One line explaining the scale, shown whenever a human has to judge a priority.
PRIORITY_SCALE: str = (
    f"{' | '.join(priority.label for priority in TRIAGE_PRIORITIES)} "
    f"({CasePriority.CRITICAL.value} is the most urgent)"
)

"""Everything the console asks the human outside of a running team."""

from __future__ import annotations

QUIT_ANSWERS = ("", "q", "quit")


def ask_for_case_id() -> str | None:
    """Ask which case is next.

    Returns:
        The case id, or None when the human wants to stop.
    """
    try:
        answer = input("\nCase id (empty to quit): ").strip()
    except EOFError:
        return None

    return None if answer in QUIT_ANSWERS else answer

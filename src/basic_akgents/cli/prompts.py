"""Everything the console asks the human outside of a running team."""

from __future__ import annotations

from dataclasses import dataclass

from basic_akgents.terminal import ask

# Ways to say "stop", next to Ctrl-D and Ctrl-C.
QUIT_COMMANDS = ("q", "quit", "exit")

# Ways to ask for the list of commands, an empty line included.
HELP_COMMANDS = ("", "h", "?", "help")

# Usage and one line of explanation, in the order they are printed.
COMMANDS: tuple[tuple[str, str], ...] = (
    ("<case id>", "Handle a case in a team of its own, e.g. case_1"),
    ("cases", "The case store as it is right now, priorities included"),
    ("teams [all]", "The teams in the event store, 'all' keeps the deleted ones"),
    ("team [ref]", "One team in full: structure, metadata, agent states"),
    ("card", "The card a case team is created from, without creating one"),
    ("events [ref] [n]", "The persisted event stream of one team, 'all' for everything"),
    ("feed [n]", "The messages the tap captured this session"),
    ("follow", "Echo every message while a case runs, on or off"),
    ("resume [ref]", "Rebuild a stopped team and hand it its case again"),
    ("help", "This list"),
    ("quit", "Stop, 'q' and Ctrl-D do the same"),
)

# What a `[ref]` accepts, printed under the list.
COMMANDS_NOTE = (
    "[ref] is a number from 'teams', the first characters of a team id, "
    "or nothing for the team used last."
)


@dataclass(frozen=True)
class Command:
    """One line the human typed, split into a verb and the rest.

    Attributes:
        name: First word, lowercased: the verb, or a case id.
        argument: Everything after the first word, as typed.
        line: The whole line, as typed.
    """

    name: str
    argument: str
    line: str


def parse_command(line: str) -> Command:
    """Split a typed line into a verb and its argument.

    Args:
        line: What the human typed.

    Returns:
        The parsed command.
    """
    stripped = line.strip()
    name, _, argument = stripped.partition(" ")

    return Command(name=name.lower(), argument=argument.strip(), line=stripped)


def ask_for_command() -> Command | None:
    """Ask what to do next.

    Returns:
        The command, or None when the human wants to stop.
    """
    try:
        line = ask("\n(help for the commands) > ")
    except (EOFError, KeyboardInterrupt):
        return None

    command = parse_command(line)

    return None if command.name in QUIT_COMMANDS else command

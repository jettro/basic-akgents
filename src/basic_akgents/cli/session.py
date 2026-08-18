"""The prompt: one typed line, one thing done, until the human stops.

Every command is a small translation - a typed reference into a stored team, a
verb into one call on `CaseRunner` or `EventFeed` - and the answer goes straight
to `console`. Nothing here knows what a message or an agent is; that is exactly
why a different front end can replace this file and nothing else.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from akgentic.team import Process

from basic_akgents.case_model import case_id_of
from basic_akgents.case_repository import build_case_repository
from basic_akgents.case_runner import CaseRunner
from basic_akgents.case_team_card import ANY_CASE_ID, case_team_card
from basic_akgents.cli import console
from basic_akgents.cli.event_feed import EventFeed
from basic_akgents.cli.prompts import (
    COMMANDS,
    COMMANDS_NOTE,
    HELP_COMMANDS,
    Command,
    ask_for_command,
)

# Lines shown by `events` and `feed` when the human asks for no number.
DEFAULT_LINES = 25


class ConsoleSession:
    """Turns typed commands into calls on the runner and the feed.

    The last listing of `teams` is remembered, so the short commands can take a
    number from it: `team 2`, `events 2`, `resume 2`. The first characters of a
    team id work everywhere a number does, and nothing at all means "the team I
    used last".
    """

    def __init__(self, runner: CaseRunner, feed: EventFeed, requester_id: str) -> None:
        """Wire the session to the two things it drives.

        Args:
            runner: Owner of the teams, and the reading side of the event store.
            feed: Reader of the tap on the messages of every team.
            requester_id: Human the case requests are made on behalf of.
        """
        self._runner = runner
        self._feed = feed
        self._requester_id = requester_id

        self._listed: list[Process] = []
        self._last_team_id: uuid.UUID | None = None

        self._handlers: dict[str, Callable[[str], None]] = {
            "cases": self._show_cases,
            "teams": self._show_teams,
            "team": self._show_team,
            "card": self._show_card,
            "events": self._show_events,
            "feed": self._show_feed,
            "follow": self._toggle_following,
            "resume": self._resume,
            "run": self._run_case,
            **dict.fromkeys(HELP_COMMANDS, self._show_commands),
        }

    def run(self, first_case_id: str | None = None) -> None:
        """Read commands until the human stops asking for them.

        Args:
            first_case_id: Case to handle right away, from the command line.
        """
        self._show_cases("")
        self._show_commands("")

        if first_case_id:
            self._run_case(first_case_id)

        while (command := ask_for_command()) is not None:
            self._dispatch(command)

    def _dispatch(self, command: Command) -> None:
        """Do what one typed line asks for.

        Args:
            command: The parsed line. An unknown verb is read as a case id, so
                typing `case_1` keeps working next to `run case_1`.
        """
        handler = self._handlers.get(command.name)

        if handler is None:
            self._run_case(command.line)
            return

        handler(command.argument)

    def _show_commands(self, argument: str) -> None:
        """Show what can be typed."""
        console.print_commands(COMMANDS, COMMANDS_NOTE)

    def _show_cases(self, argument: str) -> None:
        """Show the case store as it is right now.

        The console reads the same store instance the team writes through
        `@CaseRepository`: one backend per dotted path, so the priority a run
        just recorded is in here.
        """
        console.print_cases(build_case_repository().list_cases())

    def _show_card(self, argument: str) -> None:
        """Show the card a case team is created from, without creating one."""
        console.print_team(case_team_card(case_id=ANY_CASE_ID))

    def _show_teams(self, argument: str) -> None:
        """List the stored teams, `all` including the deleted ones."""
        include_deleted = argument.strip().lower() in ("all", "deleted")
        self._listed = self._runner.list_teams(include_deleted=include_deleted)

        console.print_teams(self._listed)

    def _show_team(self, argument: str) -> None:
        """Show one stored team in full."""
        process = self._resolve(argument)

        if process is None:
            console.print_error(self._no_team(argument))
            return

        events = self._runner.load_events(process.team_id)
        states = self._runner.load_agent_states(process.team_id)
        self._last_team_id = process.team_id

        console.print_team_details(process, event_count=len(events), states=states)

    def _show_events(self, argument: str) -> None:
        """Show the persisted event stream of one team, the tail of it by default."""
        reference, _, size = argument.partition(" ")
        process = self._resolve(reference)

        if process is None:
            console.print_error(self._no_team(reference))
            return

        events = self._runner.load_events(process.team_id)
        self._last_team_id = process.team_id

        shown = events if size.strip().lower() == "all" else events[-_lines(size) :]

        console.print_events(process.team_id, shown, total=len(events))

    def _show_feed(self, argument: str) -> None:
        """Show what the tap captured this session."""
        console.print_feed(
            self._feed.recent(_lines(argument)),
            captured=self._feed.captured,
            dropped=self._feed.dropped,
            following=self._feed.following,
        )

    def _toggle_following(self, argument: str) -> None:
        """Switch the live echo of the feed on or off."""
        console.print_following(self._feed.toggle_following(), self._feed.log_path)

    def _resume(self, argument: str) -> None:
        """Rebuild a stopped team and hand it its own case again."""
        process = self._resolve(argument)

        if process is None:
            console.print_error(self._no_team(argument))
            return

        if not case_id_of(process):
            console.print_error("That team has no case metadata, so there is nothing to resume.")
            return

        try:
            result = self._runner.resume_case(process.team_id, self._requester_id)
        except ValueError as error:
            # Only a STOPPED team may resume: a team left RUNNING by a killed
            # process is refused, and so is a deleted one.
            console.print_error(str(error))
            return

        self._remember(result.team_id)
        console.print_case_result(result)

    def _run_case(self, argument: str) -> None:
        """Handle one case in a team of its own."""
        case_id = argument.strip()

        if not case_id:
            console.print_error("Which case? Type a case id, 'cases' shows them.")
            return

        result = self._runner.run_case(case_id, self._requester_id)

        self._remember(result.team_id)
        console.print_case_result(result)

    def _remember(self, team_id: uuid.UUID) -> None:
        """Keep the team that just worked, and drop the stale listing.

        Args:
            team_id: Team `team`, `events` and `resume` default to from now on.
        """
        self._last_team_id = team_id

        # Statuses changed and a run added a team; the numbers stay stable
        # because the listing is ordered oldest first.
        self._listed = []

    def _teams(self) -> list[Process]:
        """The listing the numbers refer to, read from the store when needed."""
        if not self._listed:
            self._listed = self._runner.list_teams()

        return self._listed

    def _resolve(self, reference: str) -> Process | None:
        """Find the team a typed reference points at.

        Args:
            reference: A number from the listing, the first characters of a team
                id, or nothing for the team used last.

        Returns:
            The stored team, or None when the reference fits no single one.
        """
        teams = self._teams()
        wanted = reference.strip().lower()

        if not wanted:
            return next((p for p in teams if p.team_id == self._last_team_id), None)

        if wanted.isdigit():
            index = int(wanted)
            return teams[index - 1] if 1 <= index <= len(teams) else None

        matches = [p for p in teams if str(p.team_id).startswith(wanted)]

        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _no_team(reference: str) -> str:
        """Explain that a reference points at no single team.

        Args:
            reference: What the human typed.

        Returns:
            The sentence to show.
        """
        if not reference.strip():
            return "No team used yet - 'teams' lists them, then pick one by number."

        return f"No single team matches {reference.strip()!r} - 'teams' lists them."


def _lines(argument: str) -> int:
    """Read how many lines the human asked for.

    Args:
        argument: The typed number, empty or anything else for the default.

    Returns:
        A positive number of lines.
    """
    wanted = argument.strip()

    return int(wanted) if wanted.isdigit() and int(wanted) > 0 else DEFAULT_LINES

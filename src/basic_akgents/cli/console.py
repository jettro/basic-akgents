"""Every `print` of the demo, so the rest of the code has none.

Pure rendering: these functions are given data and turn it into lines on the
terminal. Skip this file when reading the repository for the framework concepts.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from akgentic.core.agent_state import BaseState
from akgentic.core.messages import Message
from akgentic.core.messages.orchestrator import (
    EventMessage,
    NotificationMessage,
    SentMessage,
    StartMessage,
    StateChangedMessage,
)
from akgentic.team import AgentStateSnapshot, PersistedEvent, Process, TeamCard, TeamCardMember

from basic_akgents.case_model import case_id_of
from basic_akgents.case_repository import Case
from basic_akgents.case_runner import CaseRunResult

# Wide enough for a sentence, short enough to keep one message on one line.
PAYLOAD_WIDTH = 90


@dataclass(frozen=True)
class FeedLine:
    """One message of the live feed, already rendered.

    Attributes:
        team_id: Team that published the message.
        at: Moment it was captured.
        text: The rendered one-liner.
    """

    team_id: uuid.UUID | None
    at: datetime
    text: str


def _name_of(address: object) -> str:
    """Return a printable name for an actor address."""
    return getattr(address, "name", None) or "-"


def _short_id(team_id: uuid.UUID | None) -> str:
    """First block of a team id, enough to recognise a team in a list."""
    return "-" if team_id is None else str(team_id).split("-", 1)[0]


def _clock(moment: datetime | None) -> str:
    """Local time of day of a timestamp."""
    return "--:--:--" if moment is None else moment.astimezone().strftime("%H:%M:%S")


def _stamp(moment: datetime | None) -> str:
    """Local date and time of a timestamp."""
    return "-" if moment is None else moment.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _one_line(text: str, width: int = PAYLOAD_WIDTH) -> str:
    """Squeeze any text into a single line of at most `width` characters."""
    single = " ".join(text.split())
    return single if len(single) <= width else f"{single[: width - 3]}..."


def _state_summary(state: BaseState) -> str:
    """Render a state snapshot as `StateClass(field=value, ...)`."""
    fields = ", ".join(
        f"{key}={value}" for key, value in state.model_dump().items() if not key.startswith("__")
    )
    return _one_line(f"{type(state).__name__}({fields})")


def _payload_of(message: Message) -> str:
    """Render what a message carries, one telemetry type at a time."""
    if isinstance(message, SentMessage):
        return _one_line(f"{type(message.message).__name__} {_payload_of(message.message)}")

    if isinstance(message, StartMessage):
        return f"{message.config.name} ({message.config.role})"

    if isinstance(message, StateChangedMessage):
        return _state_summary(message.state)

    if isinstance(message, EventMessage):
        return _one_line(str(message.event))

    if isinstance(message, NotificationMessage):
        return _one_line(f"{message.content_type or ''} {message.content}")

    return _one_line(str(getattr(message, "content", "")))


def render_event(message: Message) -> str:
    """Render one message as a single line: what it is, where it went, what it carried.

    Args:
        message: Message taken from a live feed or from the persisted stream.

    Returns:
        The rendered line, without a trailing newline.
    """
    route = f"{_name_of(message.sender)} -> {_name_of(message.recipient)}"
    return f"{type(message).__name__:<22} {route:<34} {_payload_of(message)}".rstrip()


def print_intro(event_store_dir: Path, log_path: Path | None) -> None:
    """Say where the two files of this run live.

    Args:
        event_store_dir: Directory the event streams of the teams land in.
        log_path: File the live feed is written to, None when it is not written.
    """
    print(f"\nEvent store   : {event_store_dir}")

    if log_path is not None:
        print(f"Live feed     : {log_path}")
        print(f"Second panel  : tail -f {log_path}   (in another terminal)")


def print_commands(commands: Sequence[tuple[str, str]], note: str = "") -> None:
    """Show what can be typed at the prompt.

    Args:
        commands: Pairs of usage and description.
        note: Sentence printed under the list, empty for none.
    """
    print("\nCommands:")
    for usage, description in commands:
        print(f"  {usage:<18} {description}")

    if note:
        print(f"  {note}")


def print_cases(cases: Iterable[Case]) -> None:
    """Show what is in the case system right now, priority 0 means it needs triage.

    Args:
        cases: Cases as the store holds them.
    """
    print("\nCases in the case store:")
    for case in cases:
        print(f"  {case.case_id} : priority {case.case_priority.label:<12} {case.case_description}")
        for action in case.actions:
            print(f"           audit    {action}")


def print_member_tree(member: TeamCardMember, indent: int = 0) -> None:
    """Print a `TeamCardMember` tree with indentation.

    Args:
        member: Member to print, children included.
        indent: Current nesting level.
    """
    prefix = "  " * indent
    role = member.card.role
    name = member.card.config.name
    hc = member.headcount
    subs = len(member.members)
    print(f"{prefix}- {name} (role={role}, headcount={hc}, subordinates={subs})")
    for child in member.members:
        print_member_tree(child, indent + 1)


def print_team(team_card: TeamCard) -> None:
    """Show the shape of the team that is created per case.

    Args:
        team_card: Card describing the team.
    """
    print(f"\nTeam: {team_card.name}")
    print(f"  {team_card.description}")
    print("Entry point:")
    print_member_tree(team_card.entry_point, indent=1)
    print("Members:")
    for member in team_card.members:
        print_member_tree(member, indent=1)
    print("Message types:")
    for message_type in team_card.message_types:
        print(f"  - {message_type.__name__} (the type a plain string is wrapped in)")
    print(f"Metadata type: {getattr(team_card.metadata_type, '__name__', '-')}")


def print_teams(processes: Sequence[Process]) -> None:
    """List the teams the event store knows, numbered so they can be picked.

    Args:
        processes: Stored teams, in the order they were created.
    """
    print("\nTeams in the event store:")

    if not processes:
        print("  (none yet - run a case first)")
        return

    print(f"  {'#':>2}  {'team id':<9} {'status':<8} {'case':<10} {'created':<20} card")
    for index, process in enumerate(processes, start=1):
        print(
            f"  {index:>2}  {_short_id(process.team_id):<9} {process.status.value:<8} "
            f"{case_id_of(process) or '-':<10} {_stamp(process.created_at):<20} "
            f"{process.team_card.name}"
        )
    print("  Pick one by number or by the first characters of its id.")


def print_team_details(
    process: Process,
    event_count: int,
    states: Sequence[AgentStateSnapshot],
) -> None:
    """Show everything the store knows about one team.

    Args:
        process: The stored team.
        event_count: Number of persisted events of this team.
        states: Latest state snapshot per agent.
    """
    print(f"\nTeam {process.team_id}")
    print(f"  card      : {process.team_card.name} - {process.team_card.description}")
    print(f"  status    : {process.status.value}")
    print(f"  case      : {case_id_of(process) or '-'}")
    print(f"  owner     : {process.user_id or '-'}")
    print(f"  created   : {_stamp(process.created_at)}")
    print(f"  updated   : {_stamp(process.updated_at)}")
    print(f"  metadata  : {process.metadata_indexes or '-'}")
    print(f"  events    : {event_count} persisted")

    print("Structure, as it was stored with the team:")
    print_member_tree(process.team_card.entry_point, indent=1)
    for member in process.team_card.members:
        print_member_tree(member, indent=1)

    print("Agent states, the last snapshot of each:")
    if not states:
        print("  (none)")
    for snapshot in states:
        name = snapshot.name or snapshot.agent_id
        print(f"  - {name:<18} {_clock(snapshot.updated_at)}  {_state_summary(snapshot.state)}")


def print_events(team_id: uuid.UUID, events: Sequence[PersistedEvent], total: int) -> None:
    """Show the persisted event stream of one team.

    Args:
        team_id: Team the events belong to.
        events: The events to show, in sequence order.
        total: How many events the team has in total.
    """
    print(f"\nEvents of team {_short_id(team_id)} - showing {len(events)} of {total}")

    if not events:
        print("  (none)")
        return

    for persisted in events:
        print(
            f"  {persisted.sequence:>4}  {_clock(persisted.timestamp)}  {render_event(persisted.event)}"
        )

    if len(events) < total:
        print("  Add 'all' to see the whole stream.")


def print_feed_line(line: FeedLine) -> None:
    """Echo one message of the live feed while a team is working.

    Args:
        line: The captured message.
    """
    print(f"| {_clock(line.at)} {_short_id(line.team_id)} {line.text}")


def print_feed(lines: Sequence[FeedLine], captured: int, dropped: int, following: bool) -> None:
    """Show the tail of what the tap captured this session.

    Args:
        lines: The captured messages to show, oldest first.
        captured: How many messages were captured since the start.
        dropped: How many were dropped because the feed fell behind.
        following: Whether every new message is echoed as it arrives.
    """
    print(f"\nLive feed - {captured} captured, {dropped} dropped, following={following}")

    if not lines:
        print("  (nothing captured yet - run or resume a case)")
        return

    for line in lines:
        print_feed_line(line)


def print_following(following: bool, log_path: Path | None) -> None:
    """Report the new state of the live echo.

    Args:
        following: Whether every new message is echoed as it arrives.
        log_path: File the live feed is written to, None when it is not written.
    """
    if following:
        print("\nFollowing: every message is echoed while a case runs, mixed in with the")
        print("questions of the team. 'follow' again to stop.")
        return

    print("\nNot following any more, 'feed' still shows what was captured.")

    if log_path is not None:
        print(f"For a panel of its own: tail -f {log_path}")


def print_case_result(result: CaseRunResult) -> None:
    """Tell the human how the team finished, or that it did not.

    Args:
        result: Outcome of one case run.
    """
    if result.event is None:
        print(f"\n[Case {result.case_id}] Timed out waiting for the case to be handled.")
    else:
        print(
            f"\n[Case {result.event.case_id}] {result.event.outcome}, priority {result.event.case_priority.label}"
        )

    origin = "resumed team" if result.resumed else "team"
    print(
        f"=== {result.message_count} messages, {result.state_count} agent states, "
        f"{origin} {result.team_id} ==="
    )


def print_error(text: str) -> None:
    """Report something the human asked for but cannot have.

    Args:
        text: What went wrong, in one sentence.
    """
    print(f"\n! {text}")

"""Every `print` of the demo, so the rest of the code has none.

Pure rendering: these functions are given data and turn it into `rich` output on
the terminal - tables for the listings, a tree for the shape of a team, a panel
for a result, and one coloured line per message. Skip this file when reading the
repository for the framework concepts.

The colours are not chosen here. `basic_akgents.terminal` holds the theme and the
one console instance; everything below only names what a thing is - `heading`,
`priority.critical`, `msg.telemetry` - and lets the theme decide.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from akgentic.core.agent_state import BaseState
from akgentic.core.messages import Message, ResultMessage, UserMessage
from akgentic.core.messages.orchestrator import (
    ErrorMessage,
    EventMessage,
    NotificationMessage,
    ProcessedMessage,
    ReceivedMessage,
    SentMessage,
    StartMessage,
    StateChangedMessage,
    StopMessage,
    WarningMessage,
)
from akgentic.team import AgentStateSnapshot, PersistedEvent, Process, TeamCard, TeamCardMember
from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from basic_akgents.case_model import case_id_of
from basic_akgents.case_priority import CasePriority
from basic_akgents.case_repository import Case
from basic_akgents.case_runner import CaseRunResult
from basic_akgents.cli.terminal import console as out

# Wide enough for a sentence, short enough to keep one message on one line.
PAYLOAD_WIDTH = 90

# The same for a state snapshot in the panel of one team, which has less room.
SNAPSHOT_WIDTH = 64

# How loud a message is printed, most specific type first: `ErrorMessage` and
# `WarningMessage` are `NotificationMessage`s, so they have to be tested before
# it. Everything the framework itself sends is telemetry and stays dim; what is
# left over is a message of this project, and that is what one wants to read.
MESSAGE_STYLES: tuple[tuple[type[Message], str], ...] = (
    (ErrorMessage, "msg.error"),
    (WarningMessage, "msg.warning"),
    (NotificationMessage, "msg.telemetry"),
    (StateChangedMessage, "msg.state"),
    (EventMessage, "msg.event"),
    (UserMessage, "msg.human"),
    (ResultMessage, "msg.result"),
    (StartMessage, "msg.telemetry"),
    (StopMessage, "msg.telemetry"),
    (SentMessage, "msg.telemetry"),
    (ReceivedMessage, "msg.telemetry"),
    (ProcessedMessage, "msg.telemetry"),
)

# The status of a stored team; anything the framework adds later stays neutral.
STATUS_STYLES: dict[str, str] = {
    "running": "status.running",
    "stopped": "status.stopped",
    "deleted": "status.deleted",
}

# How a closed case reads: handled is the happy end, the shortcuts are not.
OUTCOME_STYLES: dict[str, str] = {
    "handled": "msg.result",
    "already_prioritised": "msg.warning",
    "unknown": "error",
}


@dataclass(frozen=True)
class FeedLine:
    """One message of the live feed, already rendered.

    Attributes:
        team_id: Team that published the message.
        at: Moment it was captured.
        text: The rendered one-liner, coloured. `text.plain` is the same line
            without any styling, which is what the log file gets.
    """

    team_id: uuid.UUID | None
    at: datetime
    text: Text


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


def _listing(title: str, *, header: bool = True) -> Table:
    """A table for one of the listings, all of them shaped the same.

    Args:
        title: Heading printed above the columns.
        header: Whether the columns are named; a two-column list does not need it.

    Returns:
        The empty table, columns still to be added.
    """
    return Table(
        title=title,
        title_style="heading",
        title_justify="left",
        box=box.SIMPLE_HEAD,
        header_style="label",
        show_header=header,
        show_edge=False,
        pad_edge=False,
    )


def _priority_style(priority: CasePriority) -> str:
    """Theme style of one step of the priority scale."""
    return f"priority.{priority.name.lower()}"


def _priority(priority: CasePriority) -> Text:
    """Render a priority as its label, coloured by how urgent it is."""
    return Text(priority.label, style=_priority_style(priority))


def _style_of(message: Message) -> str:
    """Theme style for one message, telemetry dim and the conversation not."""
    for message_type, style in MESSAGE_STYLES:
        if isinstance(message, message_type):
            return style

    return "msg.domain"


def _state_summary(state: BaseState, width: int = PAYLOAD_WIDTH) -> str:
    """Render a state snapshot as `StateClass(field=value, ...)`."""
    fields = ", ".join(
        f"{key}={value}" for key, value in state.model_dump().items() if not key.startswith("__")
    )
    return _one_line(f"{type(state).__name__}({fields})", width)


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


def render_event(message: Message) -> Text:
    """Render one message as a single line: what it is, where it went, what it carried.

    A `SentMessage` is a wrapper around the message that was actually sent, so
    the payload takes the colour of that inner message: the envelope is telemetry,
    what travels in it usually is not.

    Args:
        message: Message taken from a live feed or from the persisted stream.

    Returns:
        The rendered line, styled, without a trailing newline.
    """
    route = f"{_name_of(message.sender)} -> {_name_of(message.recipient)}"
    carried = message.message if isinstance(message, SentMessage) else message

    line = Text.assemble(
        (f"{type(message).__name__:<22}", _style_of(message)),
        (f" {route:<34}", "agent"),
        (f" {_payload_of(message)}", _style_of(carried)),
    )

    # `Text.rstrip` edits in place and returns nothing, unlike `str.rstrip`.
    line.rstrip()

    return line


def print_intro(event_store_dir: Path, log_path: Path | None) -> None:
    """Say where the two files of this run live.

    Args:
        event_store_dir: Directory the event streams of the teams land in.
        log_path: File the live feed is written to, None when it is not written.
    """
    where = Table.grid(padding=(0, 2))
    where.add_column(style="label", no_wrap=True)

    # Folded and not shortened: a path with an ellipsis in it cannot be copied.
    where.add_column(style="muted", overflow="fold")
    where.add_row("event store", str(event_store_dir))

    if log_path is not None:
        where.add_row("live feed", str(log_path))
        where.add_row("second panel", f"tail -f {log_path}   (in another terminal)")

    out.print()
    out.print(
        Panel(
            where,
            title="[heading]basic-akgents[/heading]",
            subtitle="[hint]one team per case[/hint]",
            border_style="team",
            expand=False,
        )
    )


def print_commands(commands: Sequence[tuple[str, str]], note: str = "") -> None:
    """Show what can be typed at the prompt.

    Args:
        commands: Pairs of usage and description.
        note: Sentence printed under the list, empty for none.
    """
    table = _listing("Commands", header=False)
    table.add_column(style="prompt", no_wrap=True)
    table.add_column(style="muted")

    for usage, description in commands:
        table.add_row(usage, description)

    out.print()
    out.print(table)

    if note:
        out.print(Text(note, style="hint"))


def print_cases(cases: Iterable[Case]) -> None:
    """Show what is in the case system right now, priority 0 means it needs triage.

    Args:
        cases: Cases as the store holds them.
    """
    table = _listing("Cases in the case store")
    table.add_column("case", style="case", no_wrap=True)
    table.add_column("priority", no_wrap=True)
    table.add_column("description")
    table.add_column("audit", style="muted")

    for case in cases:
        table.add_row(
            case.case_id,
            _priority(case.case_priority),
            case.case_description,
            "\n".join(case.actions) or "-",
        )

    out.print()
    out.print(table)


def _member_label(member: TeamCardMember) -> Text:
    """Render one member of a team card as a line of its tree."""
    return Text.assemble(
        (member.card.config.name, "agent"),
        (f"  role={member.card.role}", "muted"),
        (f", headcount={member.headcount}", "muted"),
    )


def _member_tree(member: TeamCardMember) -> Tree:
    """Build the tree of one member and everybody below it.

    Args:
        member: Member to render, children included.

    Returns:
        The tree, rooted at this member.
    """
    tree = Tree(_member_label(member), guide_style="muted")
    _grow(tree, member)

    return tree


def _grow(node: Tree, member: TeamCardMember) -> None:
    """Add the children of one member to its node, recursively.

    Args:
        node: Node of the member itself.
        member: The member whose children are added.
    """
    for child in member.members:
        _grow(node.add(_member_label(child)), child)


def print_team(team_card: TeamCard) -> None:
    """Show the shape of the team that is created per case.

    Args:
        team_card: Card describing the team.
    """
    body = Group(
        Text(team_card.description, style="muted"),
        Text("entry point", style="label"),
        _member_tree(team_card.entry_point),
        Text("members", style="label"),
        *(_member_tree(member) for member in team_card.members),
        Text("message types", style="label"),
        Text.assemble(
            *(
                (f"{message_type.__name__}  ", "msg.domain")
                for message_type in team_card.message_types
            ),
            ("(a plain string is wrapped in these)", "hint"),
        ),
        Text.assemble(
            ("metadata type ", "label"),
            (getattr(team_card.metadata_type, "__name__", "-"), "muted"),
        ),
    )

    out.print()
    out.print(
        Panel(
            body,
            title=f"[heading]Team card[/heading] [team]{team_card.name}[/team]",
            title_align="left",
            border_style="team",
            expand=False,
        )
    )


def print_teams(processes: Sequence[Process]) -> None:
    """List the teams the event store knows, numbered so they can be picked.

    Args:
        processes: Stored teams, in the order they were created.
    """
    out.print()

    if not processes:
        out.print(Text("No teams in the event store yet - run a case first.", style="hint"))
        return

    table = _listing("Teams in the event store")
    table.add_column("#", justify="right", style="prompt", no_wrap=True)
    table.add_column("team id", style="team", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("case", style="case", no_wrap=True)
    table.add_column("created", style="muted", no_wrap=True)
    table.add_column("card", style="muted")

    for index, process in enumerate(processes, start=1):
        table.add_row(
            str(index),
            _short_id(process.team_id),
            Text(process.status.value, style=STATUS_STYLES.get(process.status.value, "muted")),
            case_id_of(process) or "-",
            _stamp(process.created_at),
            process.team_card.name,
        )

    out.print(table)
    out.print(Text("Pick one by number or by the first characters of its id.", style="hint"))


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
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="label", no_wrap=True)
    facts.add_column()
    facts.add_row("card", Text(f"{process.team_card.name} - {process.team_card.description}"))
    facts.add_row(
        "status",
        Text(process.status.value, style=STATUS_STYLES.get(process.status.value, "muted")),
    )
    facts.add_row("case", Text(case_id_of(process) or "-", style="case"))
    facts.add_row("owner", Text(process.user_id or "-"))
    facts.add_row("created", Text(_stamp(process.created_at), style="muted"))
    facts.add_row("updated", Text(_stamp(process.updated_at), style="muted"))
    facts.add_row("metadata", Text(str(process.metadata_indexes or "-"), style="muted"))
    facts.add_row("events", Text(f"{event_count} persisted", style="muted"))

    snapshots = Table.grid(padding=(0, 2))
    snapshots.add_column(style="agent", no_wrap=True)
    snapshots.add_column(style="muted", no_wrap=True)
    snapshots.add_column(style="msg.state")

    for snapshot in states:
        snapshots.add_row(
            snapshot.name or snapshot.agent_id,
            _clock(snapshot.updated_at),
            # Shorter than a feed line: this one shares its row with a name and
            # a clock, and sits inside a panel that costs width of its own.
            _state_summary(snapshot.state, width=SNAPSHOT_WIDTH),
        )

    body = Group(
        facts,
        Text("structure, as it was stored with the team", style="label"),
        _member_tree(process.team_card.entry_point),
        *(_member_tree(member) for member in process.team_card.members),
        Text("agent states, the last snapshot of each", style="label"),
        snapshots if states else Text("(none)", style="hint"),
    )

    out.print()
    out.print(
        Panel(
            body,
            title=f"[heading]Team[/heading] [team]{process.team_id}[/team]",
            title_align="left",
            border_style="team",
        )
    )


def print_events(team_id: uuid.UUID, events: Sequence[PersistedEvent], total: int) -> None:
    """Show the persisted event stream of one team.

    Lines and not a table: a rendered message asks for far more width than a
    terminal has, and a table pays for that by squeezing the narrow columns down
    to an ellipsis. A prefix plus a soft wrapped line leaves the wrapping to the
    terminal, exactly like the live feed does.

    Args:
        team_id: Team the events belong to.
        events: The events to show, in sequence order.
        total: How many events the team has in total.
    """
    out.print()

    if not events:
        out.print(Text(f"Team {_short_id(team_id)} has no persisted events.", style="hint"))
        return

    out.print(
        Text.assemble(
            (f"Events of team {_short_id(team_id)}", "heading"),
            (f" - showing {len(events)} of {total}", "muted"),
        )
    )

    for persisted in events:
        prefix = Text.assemble(
            (f"{persisted.sequence:>5} ", "muted"),
            (f"{_clock(persisted.timestamp)} ", "muted"),
        )
        out.print(prefix.append_text(render_event(persisted.event)), soft_wrap=True)

    if len(events) < total:
        out.print(Text("Add 'all' to see the whole stream.", style="hint"))


def print_feed_line(line: FeedLine) -> None:
    """Echo one message of the live feed while a team is working.

    Args:
        line: The captured message.
    """
    prefix = Text.assemble(
        ("| ", "muted"),
        (f"{_clock(line.at)} ", "muted"),
        (f"{_short_id(line.team_id)} ", "team"),
    )

    # Soft wrapped, so a long line is left to the terminal instead of being cut
    # off at the width rich assumes.
    out.print(prefix.append_text(line.text), soft_wrap=True)


def print_feed(lines: Sequence[FeedLine], captured: int, dropped: int, following: bool) -> None:
    """Show the tail of what the tap captured this session.

    Args:
        lines: The captured messages to show, oldest first.
        captured: How many messages were captured since the start.
        dropped: How many were dropped because the feed fell behind.
        following: Whether every new message is echoed as it arrives.
    """
    out.print()
    out.print(
        Text.assemble(
            ("Live feed", "heading"),
            (f" - {captured} captured, ", "muted"),
            (f"{dropped} dropped", "error" if dropped else "muted"),
            (", following=", "muted"),
            (str(following), "msg.result" if following else "muted"),
        )
    )

    if not lines:
        out.print(Text("Nothing captured yet - run or resume a case.", style="hint"))
        return

    for line in lines:
        print_feed_line(line)


def print_following(following: bool, log_path: Path | None) -> None:
    """Report the new state of the live echo.

    Args:
        following: Whether every new message is echoed as it arrives.
        log_path: File the live feed is written to, None when it is not written.
    """
    out.print()

    if following:
        out.print(
            Text(
                "Following: every message is echoed while a case runs, mixed in with the"
                " questions of the team. 'follow' again to stop.",
                style="msg.result",
            )
        )
        return

    out.print(Text("Not following any more, 'feed' still shows what was captured.", style="muted"))

    if log_path is not None:
        out.print(Text(f"For a panel of its own: tail -f {log_path}", style="hint"))


def print_case_result(result: CaseRunResult) -> None:
    """Tell the human how the team finished, or that it did not.

    Args:
        result: Outcome of one case run.
    """
    facts = Table.grid(padding=(0, 2))
    facts.add_column(style="label", no_wrap=True)
    facts.add_column()

    if result.event is None:
        style = "error"
        case_id = result.case_id
        facts.add_row("outcome", Text("timed out waiting for the case", style=style))
    else:
        style = OUTCOME_STYLES.get(result.event.outcome, "msg.warning")
        case_id = result.event.case_id
        facts.add_row("outcome", Text(result.event.outcome, style=style))
        facts.add_row("priority", _priority(result.event.case_priority))

    origin = "resumed team" if result.resumed else "team"
    facts.add_row(origin, Text(str(result.team_id), style="team"))
    facts.add_row(
        "recorded",
        Text(
            f"{result.message_count} messages, {result.state_count} agent states",
            style="muted",
        ),
    )

    out.print()
    out.print(
        Panel(
            facts,
            title=f"[heading]Case[/heading] [case]{case_id}[/case]",
            title_align="left",
            border_style=style,
            expand=False,
        )
    )


def print_error(text: str) -> None:
    """Report something the human asked for but cannot have.

    Args:
        text: What went wrong, in one sentence.
    """
    out.print()
    out.print(Text.assemble(("! ", "error"), (text, "error")))

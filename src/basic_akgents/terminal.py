"""The one terminal the demo writes to, and the palette it writes in.

Two layers print. The console front end in `basic_akgents.cli` does most of it,
and `CliUserProxyAgent` does the rest: it has to ask its question on the same
terminal as everything else. Agent code may not import the front end - the ruff
configuration bans it - so the shared `rich` console lives here, beside the
agents, and both sides use this one instance.

Colour is a naming problem rather than a decorating one. Nothing outside this
file says "red"; it says what a thing *is* - `error`, `priority.critical`,
`msg.telemetry` - and the theme below decides once what that looks like. Rich
drops the colour by itself when the output is not a terminal, so a piped run or
a redirect stays plain text.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

# Semantic names only: what is printed, never how it looks.
THEME = Theme(
    {
        # The frame around a listing.
        "heading": "bold cyan",
        "label": "cyan",
        "hint": "italic grey62",
        "muted": "grey62",
        "prompt": "bold cyan",
        "error": "bold red",
        # A case and its priority: lower is more urgent, so it gets louder.
        "case": "bold white",
        "priority.unset": "grey62",
        "priority.critical": "bold red",
        "priority.high": "dark_orange",
        "priority.normal": "yellow",
        "priority.low": "green",
        # Teams and their members.
        "team": "bold blue",
        "agent": "magenta",
        "status.running": "bold green",
        "status.stopped": "yellow",
        "status.deleted": "strike grey62",
        # One line per message: the type decides how loud it is, so the domain
        # conversation stands out from the telemetry around it.
        "msg.domain": "cyan",
        "msg.telemetry": "grey62",
        "msg.state": "blue",
        "msg.event": "bold yellow",
        "msg.human": "bold green",
        "msg.result": "green",
        "msg.warning": "yellow",
        "msg.error": "bold red",
    }
)

# `highlight=False`: rich colours numbers and quotes inside plain strings by
# itself, which fights with the styles picked above.
console = Console(theme=THEME, highlight=False)


def say(name: str, content: str, *, style: str = "msg.domain") -> None:
    """Print what an agent said to the human, framed and titled with its name.

    The content is wrapped in a `Text`, so square brackets in a case description
    are printed instead of read as markup.

    Args:
        name: Agent doing the talking.
        content: What it said.
        style: Theme style for the frame, which tells a question from a report.
    """
    console.print(
        Panel(
            Text(content),
            title=f"[agent]{name}[/agent]",
            title_align="left",
            border_style=style,
            padding=(0, 1),
            expand=False,
        )
    )


def ask(prompt: str = "> ") -> str:
    """Read one line from the human.

    Args:
        prompt: What to show in front of the cursor.

    Returns:
        The line as typed.

    Raises:
        EOFError: When there is no input left.
        KeyboardInterrupt: When the human pressed Ctrl-C.
    """
    return console.input(f"[prompt]{prompt}[/prompt]")

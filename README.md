# basic-akgents

A small, hands-on sample built on the **akgentic** agent framework (`akgentic-core`). It runs a tiny
team of agents that triages one support case: the agents do the work, a human only approves the
result.

The learning journal behind the code lives in [`notes.md`](notes.md); the framework notes and gotchas
in [`.junie/guidelines.md`](.junie/guidelines.md).

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) for dependencies and running
- `make` for the shortcuts below (optional, every target is a one-line `uv` command)

```bash
make sync     # or: uv sync
```

## Make targets

`make` without a target lists them all:

| Target | What it does |
|---|---|
| `make sync` | Install the project and its dev tools from `uv.lock` |
| `make run CASE=case_2` | Run the sample, `CASE` is optional |
| `make watch` | `tail -f data/live-feed.log`, the live event feed in a second terminal |
| `make lint` | `ruff check .` |
| `make fix` | `ruff check --fix .`, the fixes ruff can make itself |
| `make format` | `ruff format .` |
| `make format-check` | Report formatting differences without writing them |
| `make check` | `lint` + `format-check`, run this before committing |
| `make lock` / `make upgrade` | Refresh `uv.lock`, with or without bumping versions |
| `make clean` | Remove `.ruff_cache` and `__pycache__` directories |
| `make clean-data` | Remove the event store of past runs (`data/`) |

Code quality is [ruff](https://docs.astral.sh/ruff/) only; it is a dev-only dependency and its
configuration lives in `pyproject.toml`.

## Running the sample

```bash
make run CASE=case_1          # no priority yet -> proposes 3 - normal
make run CASE=case_2          # no priority yet -> proposes 1 - critical (mentions 'urgent')
make run CASE=case_4          # already 1 - critical -> closes as already_prioritised
make run CASE=case_42         # unknown case -> the run closes right away
make run                      # no case -> lists the store and waits for a command
```

Without `make`, the same thing: `uv run src/main.py case_1`. Two flags are extra:
`--follow` starts with the live feed echoing, `--no-feed-log` writes no `data/live-feed.log`.

The demo store is in memory, so every session starts from the same five cases:

| Case | Description | Priority |
|---|---|---|
| `case_1` | The printer on the second floor jams on every duplex job | not set |
| `case_2` | Mail server is down for the whole department, urgent | not set |
| `case_3` | New colleague starts on Monday and needs a mail account | not set |
| `case_4` | Laptop was stolen from a car and has to be wiped | 1 - critical |
| `case_5` | Request for a second monitor for the finance team | 4 - low |

### The prompt

A case is one command among several. Anything the prompt does not recognise is read as a case id, so
typing `case_1` still starts a team:

| Command | What it does |
|---|---|
| `<case id>` | Handle a case in a team of its own, e.g. `case_1` |
| `cases` | The case store as it is *now*, so a priority a run just wrote is visible |
| `teams [all]` | The teams in the event store, numbered; `all` keeps the deleted ones |
| `team [ref]` | One team in full: structure, metadata, event count, agent states |
| `card` | The card a case team is created from, without creating one |
| `events [ref] [n]` | The persisted event stream of one team, `all` for the whole thing |
| `feed [n]` | The messages the tap captured this session, across all teams |
| `follow` | Echo every message while a case runs, on or off |
| `resume [ref]` | Rebuild a stopped team from the store and hand it its case again |
| `help`, `quit` | The list, and stop (`q` and Ctrl-D do the same) |

`[ref]` is a number from `teams`, the first characters of a team id, or nothing at all for the team
used last.

### Watching the messages

Every team reports every message to its orchestrator, and `EventTap` - a subscriber shared by all
teams - hands all of them to the console. One terminal cannot show a prompt and a stream at the same
time, so there are three ways to look at them:

- `feed` prints the tail afterwards, and `events` reads the stream back out of the store.
- `follow` echoes each message the moment it arrives, mixed in with the questions of the team.
- `data/live-feed.log` gets one line per message: `tail -f` it in a second terminal and the stream
  never touches the prompt. That is the second panel, without a TUI.

### Answering the approval question

The team proposes a priority and explains why; you decide:

| Input | Meaning |
|---|---|
| `Enter` or `y` | approve the proposed priority |
| `n` | reject it, the case keeps its current priority |
| `1` - `4` | override with your own priority and approve in one step |

The scale counts down: `1 - critical | 2 - high | 3 - normal | 4 - low`.

### A run from start to finish

```
$ uv run src/main.py case_2

Event store   : /.../basic-akgents/data
Live feed     : /.../basic-akgents/data/live-feed.log
Second panel  : tail -f /.../basic-akgents/data/live-feed.log   (in another terminal)

Cases in the case store:
  case_1 : priority 0 - not set  The printer on the second floor jams on every duplex job
  ...

Commands:
  <case id>          Handle a case in a team of its own, e.g. case_1
  ...

[@CaseCoordinator] Case case_2
  description : Mail server is down for the whole department, urgent
  reported by : jettro
  proposal    : priority 1 - critical, because the case mentions 'urgent'
  scale       : 1 - critical | 2 - high | 3 - normal | 4 - low (1 is the most urgent)
Approve priority 1 - critical? [Enter/y] approve, [n] reject, or type another number (1-4)
>

[@CaseCoordinator] Case case_2 has been triaged.
  description : Mail server is down for the whole department, urgent
  priority    : 1 - critical (approved by jettro)

[Case case_2] handled, priority 1 - critical
=== 43 messages, 4 agent states, team 896a6f59-773a-4f26-8e90-9f6a785360bb ===

(help for the commands) > teams

Teams in the event store:
   #  team id   status   case       created              card
   1  896a6f59  stopped  case_2     2026-08-18 20:57:59  case-handling-team
  Pick one by number or by the first characters of its id.

(help for the commands) > resume 1

[@CaseCoordinator] Case case_2 was not triaged - the case already has priority 1 - critical.
  ...
=== 67 messages, 4 agent states, resumed team 896a6f59-773a-4f26-8e90-9f6a785360bb ===
```

`card` prints the team from its card, so the shape of a team is visible without starting one. The
counts at the end come from the orchestrator, which records every message and every state change:
compare `case_2` (43 messages) with `case_4` (25 messages) to see the "already prioritised" shortcut
in the telemetry. A resumed team starts at the 43 messages it already had, which is the replayed
history - visible in `events 1`, invisible in `feed`, because a replay is not something happening now.

## What happens under the hood

One team handles one case. The team is described in one place,
`src/basic_akgents/case_team_card.py`: an `AgentCard` per role, the console proxy included. Naming the
proxy there rather than passing it in keeps the callers free of wiring - a different front end writes
its own card function. `CaseRunner` creates a team from that card per case and stops it again when the
case is closed.

```
case-handling-team
  ├── @UserProxy             entry point: prints questions and reads your answer
  └── @CaseCoordinator       drives the case, asks the human to approve
        ├── @CaseTriage      assesses the case and proposes a priority
        └── @CaseRepository  owns the case store, the only agent that reads and writes it
```

1. The runner sends a `HandleCaseRequest` into the team.
2. The coordinator asks `@CaseTriage` for an assessment - no human involved yet.
3. Triage asks `@CaseRepository` for the case (`CaseInformationRequest`) and gets it back in a
   `CaseInformationResponse`.
4. Triage answers with the *proposed* priority plus the reason; nothing is stored.
5. The coordinator asks the human, through `@UserProxy`, to approve that proposal.
6. Your answer becomes a `CasePriorityDecision`; triage turns it into a `CaseUpdateRequest`, and
   `@CaseRepository` is the one that writes it.
7. The coordinator reports the outcome to `@UserProxy`, which prints it, and announces a `CaseClosed`
   event; on that event the runner stops the team and the console asks for the next command.

Two shortcuts skip the human: an unknown case id closes the run as `unknown`, and a case that already
has a priority closes as `already_prioritised`.

### A stopped team is not a gone team

`stop_team` marks the team `STOPPED` and leaves everything behind in `data/<team id>/`: the card it was
created from, its metadata, its whole event stream and the last state of every agent. That is what the
reading commands show, and `resume` builds the team again from it - the agents come back from the
`StartMessage`s, each one gets its snapshot back, and the history is replayed into the orchestrator.
Replay reaches *subscribers*, not agents, so nothing that happened before happens twice; a fresh
`HandleCaseRequest` is what puts the team back to work.

The case store is a different story: it lives in memory, so it starts from the table above in every
new process. Resume a team from an earlier session and its case needs triage again; resume one from
this session and the guard closes it as `already_prioritised`.

## Project layout

| File | Contents |
|---|---|
| `Makefile` | Shortcuts for syncing, running the sample and the quality checks |
| `pyproject.toml` | Project metadata, the dev-only ruff dependency and the ruff configuration |
| `src/main.py` | Entry point, so `uv run src/main.py <case id>` keeps working |
| `src/basic_akgents/cli/app.py` | Wires the feed, the runner and the prompt together |
| `src/basic_akgents/cli/session.py` | `ConsoleSession`, one typed command translated into one call |
| `src/basic_akgents/cli/prompts.py` | The command catalogue and the parser for a typed line |
| `src/basic_akgents/cli/console.py` | Every `print` of the demo, including the message renderer |
| `src/basic_akgents/cli/event_feed.py` | `EventFeed`, drains the tap: tail, live echo, log file |
| `src/basic_akgents/event_tap.py` | `EventTap`, a subscriber that keeps every message of every team |
| `src/basic_akgents/case_team_card.py` | `case_team_card`, the whole declaration of a case team |
| `src/basic_akgents/case_runner.py` | `CaseRunner`, the teams and the reading side of the event store |
| `src/basic_akgents/case_coordinator.py` | `CaseCoordinatorAgent`, the approval flow |
| `src/basic_akgents/case_triage.py` | `CaseTriageAgent`, proposes the priority and hands the verdict on |
| `src/basic_akgents/case_repository_agent.py` | `CaseRepositoryAgent` and the case information / update messages |
| `src/basic_akgents/cli_user_proxy.py` | `CliUserProxyAgent`, the human-in-the-loop bridge to stdin |
| `src/basic_akgents/case_repository.py` | `Case`, the `CaseRepository` protocol and the in-memory dummy |
| `src/basic_akgents/case_priority.py` | `CasePriority` scale and its labels |
| `src/basic_akgents/case_model.py` | `CaseConfig`, the config shared by every agent on the case |

## Things to try

- Reject a proposal (`n`) and watch the case keep its `not set` priority - a rejection means "not this
  priority", not "never triage this".
- Override the proposal by typing another number and see it in the approval line of the report.
- Run `case_4` or `case_5` to see the guard that refuses a case which was already prioritised. The
  store is in memory, so each session starts from the table above again.
- Handle a case, then `cases`: the priority the team wrote is in the store, and the audit line says who
  approved it.
- Handle a case and `resume` its team: the same agents come back, and the guard now refuses the case
  they triaged themselves a minute ago.
- Compare `events 1` with `feed`: the store keeps what was sent, received and processed, while the
  live tap also sees every `StateChangedMessage` - state snapshots go to a file of their own.
- Open a second terminal on `tail -f data/live-feed.log` and run a case with `follow` off: the
  conversation appears there, message by message, while the prompt stays clean.
- Swap the backend in `case_team_card` for your own implementation of `CaseRepository`; only
  `@CaseRepository` ever holds it, so no other agent notices.
- Point the proxy card in `case_team_card` at another `UserProxy` subclass to replace the console
  bridge; nothing else in the team changes.
- Ask the orchestrator what `@CaseRepository` did: its state snapshot counts the reads and writes, so
  every touch of the case store is visible in the telemetry.

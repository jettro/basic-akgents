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
make run                      # no case -> lists the store, then asks for a case id
```

Without `make`, the same thing: `uv run src/main.py case_1`.

The demo store is in memory, so every run starts from the same five cases:

| Case | Description | Priority |
|---|---|---|
| `case_1` | The printer on the second floor jams on every duplex job | not set |
| `case_2` | Mail server is down for the whole department, urgent | not set |
| `case_3` | New colleague starts on Monday and needs a mail account | not set |
| `case_4` | Laptop was stolen from a car and has to be wiped | 1 - critical |
| `case_5` | Request for a second monitor for the finance team | 4 - low |

### Answering the prompt

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
Cases in the demo store:
  case_1 : priority 0 - not set  The printer on the second floor jams on every duplex job
  ...

Team: case-handling-team
Entry point:
  - @UserProxy (role=UserProxy, headcount=1, subordinates=0)
Members:
  - @CaseCoordinator (role=Coordinator, headcount=1, subordinates=2)
    - @CaseTriage (role=Triage, headcount=1, subordinates=0)
    - @CaseRepository (role=Repository, headcount=1, subordinates=0)

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

Case id (empty to quit):
```

The team is printed from the card before anything runs, so the shape of a team is visible without
starting one. The counts at the end come from the orchestrator, which records every message and every
state change: compare `case_2` (43 messages) with `case_4` (25 messages) to see the "already
prioritised" shortcut in the telemetry.

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
   event; on that event the runner stops the team and the console asks for the next case.

Two shortcuts skip the human: an unknown case id closes the run as `unknown`, and a case that already
has a priority closes as `already_prioritised`.

## Project layout

| File | Contents |
|---|---|
| `Makefile` | Shortcuts for syncing, running the sample and the quality checks |
| `pyproject.toml` | Project metadata, the dev-only ruff dependency and the ruff configuration |
| `src/main.py` | Entry point, so `uv run src/main.py <case id>` keeps working |
| `src/basic_akgents/cli/app.py` | The console application: read a case id, run it, show the outcome |
| `src/basic_akgents/case_team_card.py` | `case_team_card`, the whole declaration of a case team |
| `src/basic_akgents/case_runner.py` | `CaseRunner`, one short-lived team per case and its lifecycle |
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
  store is in memory, so each run starts from the table above again.
- Swap the backend in `case_team_card` for your own implementation of `CaseRepository`; only
  `@CaseRepository` ever holds it, so no other agent notices.
- Point the proxy card in `case_team_card` at another `UserProxy` subclass to replace the console
  bridge; nothing else in the team changes.
- Ask the orchestrator what `@CaseRepository` did: its state snapshot counts the reads and writes, so
  every touch of the case store is visible in the telemetry.

# basic-akgents

A small, hands-on sample built on the **akgentic** agent framework (`akgentic-core`). It runs a tiny
team of agents that triages one support case: the agents do the work, a human only approves the
result.

The learning journal behind the code lives in [`notes.md`](notes.md); the framework notes and gotchas
in [`.junie/guidelines.md`](.junie/guidelines.md).

## Requirements

- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/) for dependencies and running

```bash
uv sync
```

## Running the sample

```bash
uv run src/main.py case_1     # no priority yet -> proposes 3 - normal
uv run src/main.py case_2     # no priority yet -> proposes 1 - critical (mentions 'urgent')
uv run src/main.py case_4     # already 1 - critical -> "was not triaged"
uv run src/main.py case_42    # unknown case -> the run closes right away
uv run src/main.py            # no argument -> lists the store, then asks for a case id
```

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
[Case case_2] Team started. Triage assesses the case, you approve its priority.

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

=== Orchestrator Summary ===
Total messages: 27
Team members: 3 agents
State snapshots: 3 agents tracked
===========================
[Multi-Agent] Demo complete. Shutting down.
```

The summary at the end comes from the orchestrator, which records every message, every state change
and the team roster. Compare a run of `case_2` (27 messages) with `case_4` (15 messages) to see the
"already prioritised" shortcut in the telemetry.

## What happens under the hood

One team handles one case. `src/main.py` is the composition root: it starts the orchestrator, lets the
orchestrator create the coordinator, and lets the coordinator create its two children.

```
Orchestrator
  └── @CaseCoordinator      drives the case, asks the human to approve
        ├── @CaseTriage     reads the case, proposes a priority, stores the verdict
        └── @UserProxy      prints questions on the console and reads your answer
```

1. `main` sends a `HandleCaseRequest` to the coordinator.
2. The coordinator asks `@CaseTriage` for an assessment - no human involved yet.
3. Triage answers with the *proposed* priority plus the reason; nothing is stored.
4. The coordinator asks the human, through `@UserProxy`, to approve that proposal.
5. Your answer becomes a `CasePriorityDecision`; only then does triage write it to the case store.
6. The coordinator reports the outcome, the proxy prints it and the demo shuts down.

Two shortcuts skip the human: an unknown case id closes the run, and a case that already has a
priority is reported as "was not triaged".

## Project layout

| File | Contents |
|---|---|
| `src/main.py` | Composition root: starts the actor system, wires the agents, waits for the result |
| `src/basic_akgents/case_coordinator.py` | `CaseCoordinatorAgent`, the approval flow |
| `src/basic_akgents/case_triage.py` | `CaseTriageAgent`, proposes and persists the priority |
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
- Swap `DummyCaseRepository` in `src/main.py` for your own implementation of `CaseRepository`; the
  agents never see the difference.

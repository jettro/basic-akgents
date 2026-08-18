# Project guidelines — basic-akgents

Knowledge base for this repository. Everything below was verified against the installed
`akgentic-core` **1.5.4** in `.venv/lib/python3.12/site-packages/akgentic/` (last checked 2026-08-16).
The framework is not on PyPI docs — **the installed source in `.venv` is the reference documentation**.

---

## 1. What this project is

A personal learning repository for the **akgentic** agent framework. The goal is to understand the
*core* actor/agent concepts first (`akgentic-core`), building an own worked example rather than
reading the shipped examples only. See `notes.md` for the running learning journal.

- Python `>=3.12`, package layout `src/basic_akgents/`
- Dependency management: **uv** (`uv add <pkg>`, `uv run`, `uv sync`) — `uv.lock` is committed
- Single dependency: `akgentic-core>=1.5.4` (pulls in `pydantic` 2.13, `pykka` 4.4)
- Entry point declared in `pyproject.toml`: `basic-akgents = basic_akgents:main`

### Domain model being built

One **team per case**. Teams are lightweight and short-lived: archived when idle, reactivated when the
case needs work again. The framework deliberately does *not* support long-running teams you keep
chatting with.

| Agent | Responsibility |
|---|---|
| `CaseCoordinatorAgent` | Accepts the case, coordinates end-to-end handling |
| `CaseTriageAgent` | Checks the case, tags it, prioritises it |
| `CaseInformation` | Fetches the context for the case |
| `CaseHandler` | Proposes system changes / writes answers; needs personal data + human confirmation |
| `GenericInfoHandler` | Handles cases asking for generic answers |
| `UserProxy` | Human-in-the-loop bridge (provided by the framework) |

---

## 2. Framework mental model

```
ActorSystem  (actor_system_impl.py)
  └── Orchestrator          <- an Akgent itself; created via system.createActor(Orchestrator, ...)
        └── root agent      <- created via orchestrator.createActor(..., config=...)
              └── children  <- created via self.createActor(...) inside an agent
```

`ActorSystem.createActor` does **not** create or attach an orchestrator — it only calls
`actor_class.start(...)`. So the orchestrator must be started explicitly as the root actor, and every
other agent has to be created through `Akgent.createActor` (the only call that passes
`orchestrator`, `team_id` and `parent` down). See gotcha #12.

- `Akgent` extends `pykka.ThreadingActor` — **every agent is its own thread**; handlers run
  serialized per agent, so no locking is needed for `self.state`.
- Type parameters: `Akgent[ConfigType, StateType]`, bound to `BaseConfig` / `BaseState`.
  Always pass your *concrete* state class as the second parameter, otherwise `self.state` types wrong.
- Public API (`from akgentic.core import ...`): `Akgent`, `BaseConfig`, `AgentConfig`, `BaseState`,
  `AkgentStateObserver`, `ActorSystem`, `ExecutionContext`, `Statistics`, `ActorAddress`,
  `ActorAddressImpl`, `ActorAddressProxy`, `ActorAddressStopped`, `Orchestrator`, `EventSubscriber`,
  `UserProxy`, `AgentCard`, `AkgentDeserializeContext`.
  `ReadOnlyField` is **not** re-exported — import it from `akgentic.core.agent_config`.

### Lifecycle

1. `Akgent.__init__` — runs in the *caller's* thread. Sets `agent_id`, `team_id`, `config`, a default
   `BaseState()`, fills in `config.name`/`config.role` if empty, then emits
   `StartMessage(config=..., parent=...)` to the orchestrator.
2. `on_start()` — runs in the *actor's own* thread once started. **This is where you belong**: create
   the real state object, attach the observer, spawn children.
3. `on_receive` → `_receiveMessage` per message (telemetry sandwich, see §4).
4. `stop()` — stops all children blocking first, then self. `on_stop()` emits `StopMessage`.

Canonical `on_start`:

```python
def on_start(self) -> None:
    self.state = CaseCoordinatorState()
    self.state.observer(self)  # attaches observer AND fires the first notification
```

---

## 3. Config vs. State — the central design rule

This is the decision that shapes every agent. Investigated in depth; conclusions below are
verified by running code against the installed package, not inferred.

| | `BaseConfig` (`agent_config.py`) | `BaseState` (`agent_state.py`) |
|---|---|---|
| Lifecycle | Passed once into `__init__(config=...)`, never reassigned by the framework | Explicitly designed to be replaced: `init_state()`, `update_state()` |
| Change tracking | Published **once**, in `StartMessage` | Observer fires `notify_state_change()` → `StateChangedMessage` → orchestrator snapshot on *every* mutation |
| Intent | Identity / settings of the agent | Working data that evolves |
| Helper | `ReadOnlyField()` (schema-level `readOnly`) | none |

**Rule of thumb**

- **Config** → facts known at construction that must not change for the agent's lifetime:
  identity, `case_id`, tenant, model name, thresholds, feature flags.
- **State** → everything that changes while handling messages: status, collected tags, priority,
  gathered context, pending human confirmation.

### Immutable values belong in the config

`BaseConfig` fields: `name: str = ""`, `role: str = ""`, `squad_id: uuid.UUID | None = None`.

```python
from akgentic.core import BaseConfig
from akgentic.core.agent_config import ReadOnlyField


class CaseConfig(BaseConfig):
    """Config shared by every agent working on a single case."""

    case_id: str = ReadOnlyField(frozen=True)
```

- `ReadOnlyField(**kwargs)` just forwards to `pydantic.Field` with
  `json_schema_extra={"readOnly": True}` → it is a **schema hint only, no runtime enforcement**.
- Add `frozen=True` for the actual runtime guarantee. Verified: `c.case_id = "HACKED"` raises
  `ValidationError` (`frozen_field`), `model_dump()`/`model_validate()` round-trips fine.
- Config travels with agent identity: `StartMessage` carries it, `Orchestrator.get_team()` rebuilds
  the roster from the `StartMessage`s in history — so it survives team resume.

> **Never** set `model_config = ConfigDict(frozen=True)` on a config class.
> `Akgent.__init__` writes to the config object:
> `self.config.name = self.config.name or str(self._actor_ref)` and the same for `role`.
> A class-level freeze blows up at agent startup. Per-field `frozen=True` leaves `name`/`role` writable.

### Freezing a *state* field does NOT protect it

`Akgent.update_state()` does `{**self.state.model_dump(), **updates}` and rebuilds the object via
`deserialize_object(...)`. Because that **constructs a new instance**, Pydantic's `frozen=True` is
never triggered. Verified: direct assignment raises, but the `update_state` path silently overwrote
the "frozen" value. Config has no such rebuild path, so there `frozen=True` genuinely holds.

Putting an invariant in state also means it is re-serialized and re-snapshotted to the orchestrator on
every single state change — pure noise.

Only put an immutable value in state as a **derived copy** (never the source of truth), e.g. when a UI
subscriber consumes `StateChangedMessage` snapshots and cannot see the `StartMessage` config:
`self.state = CaseCoordinatorState(case_id=self.config.case_id)`.

### Working with state

```python
self.state.field = value
self.state.notify_state_change()  # must be called explicitly after mutation
# or, in one go:
self.update_state({"field": value})  # merge + rebuild + notify
```

- `state.observer(self)` attaches the agent as observer **and** fires an immediate notification.
- `serializable_copy()` strips `_observer` (a `PrivateAttr`) to avoid circular references.
- `init_state(new_state)` replaces the state object and carries the observer over.
- `update_state` swallows exceptions: on failure it logs and emits an `ErrorMessage` — it does *not*
  raise. Do not rely on it throwing.

---

## 4. Messages and dispatch

Base types in `akgentic/core/messages/message.py`: `Message` (`id`, `parent_id`, `team_id`,
`timestamp`, `sender`, `recipient`, `display_type`), plus `UserMessage` (`display_type="human"`) and
`ResultMessage` (`display_type="ai"`), both with a `content: str`. `StopRecursively` is a dataclass.

Define your own message types by subclassing `Message`; they serialize via `SerializableBaseModel`
(a `__model__` key records the fully qualified class for deserialization).

### Handlers

```python
def receiveMsg_CaseSubmitted(self, message: CaseSubmitted, sender: ActorAddress) -> None: ...
```

- Dispatch walks the **message MRO** and, for each match, the **actor MRO** — so a handler for a base
  message type catches subclasses.
- The `sender` parameter is optional; it is passed only if the signature declares it.
- To decline a message and let the search continue up the chain, `return self.SUPER`.
  **Any other return value, including `None`, means "handled" and stops the search.**
- Unhandled messages are only logged as a warning — they fail silently. Watch for that in tests.

### Sending

| Call | Semantics |
|---|---|
| `self.send(recipient, message)` | fire-and-forget; stamps sender/team/`parent_id`, emits `SentMessage` telemetry |
| `self.proxy_tell(addr, Akgent).method(...)` | fire-and-forget direct method call, no telemetry |
| `self.proxy_ask(addr, Akgent, timeout=...).method(...)` | **blocking** call that returns the result |

`self.send` is the normal path — it keeps the conversation thread (`parent_id`) and the telemetry
stream intact. `proxy_ask` blocks the calling agent's thread; never use it toward an agent that might
call back into you (deadlock).

Errors: an exception in a handler triggers `_handle_failure` → `ErrorMessage` to the orchestrator.
Raise `WarningError` (from `akgentic.core.agent`) for "handled, non-critical" conditions — it produces
a `WarningMessage` instead, observable without counting as a failure.

---

## 5. Orchestrator and telemetry

Every agent automatically reports to the orchestrator: `StartMessage`, `ReceivedMessage`,
`ProcessedMessage`, `SentMessage`, `StateChangedMessage`, `EventMessage`, `WarningMessage`,
`ErrorMessage`, `StopMessage`.

The `Orchestrator` (itself an `Akgent[BaseConfig, BaseState]`) keeps in memory:
message history, per-agent state snapshots (`get_states()`), per-agent LLM context, tool state, and a
team roster **computed from history** (started minus stopped).

Useful queries: `get_team()`, `get_team_member(name)`, `get_messages(sender=, message_type=)`,
`get_events(agent_id=, event_class=)`, `get_states()`, `get_metadata()` / `set_metadata()`.

From inside an agent: `self.get_team()`, `self.get_team_member("@CaseTriage")`,
`self.notify_event(obj)`. These raise `WarningError` when no orchestrator is attached.

An inactivity timer (`ORCHESTRATOR_TIMEOUT_DELAY`, default 3600s) fires `on_stop_request` on
subscribers — the orchestrator itself does not stop; a subscriber decides. Extend behaviour by
implementing the `EventSubscriber` protocol (`on_message`, `on_start`, `on_stop`, `on_stop_request`,
`set_restoring`).

Because config and state land in the persisted event stream, **never put secrets in either**.
A `case_id` is fine.

---

## 6. Creating children and sharing values across the team

`Akgent.createActor(actor_class, agent_id=None, config=None)` propagates `user_id`, `user_email`,
`team_id`, `parent`, `orchestrator` automatically, and registers the child for recursive shutdown.

**Only `squad_id` is auto-inherited** (`config.squad_id = config.squad_id or self.config.squad_id`).
Every other config field must be passed explicitly. The root `ActorSystem.createActor` generates a
`squad_id` when none is given.

Since all agents here work on one case, use a shared base config:

```python
class CaseConfig(BaseConfig):
    case_id: str = ReadOnlyField(frozen=True)


class CaseTriageConfig(CaseConfig):
    max_tags: int = 5


triage = self.createActor(
    CaseTriage,
    config=CaseTriageConfig(name="@CaseTriage", case_id=self.config.case_id),
)
```

Naming convention seen throughout the framework: agent names are prefixed with `@`
(`"@CaseTriage"`, `"@ActorSystem"`), and `get_team_member()` looks up by exactly that name.

### Injecting non-serializable dependencies (repositories, clients, events)

`createActor` takes only `actor_class`, `agent_id` and `config` — no constructor arguments — and
config/state are serialized, so a live object can go in neither. Declare the slot in `on_start` and
inject it afterwards with a setter over `proxy_tell` (a plain in-process call, passed by reference);
mailbox order guarantees the setter runs before the first message is handled.

```python
class CaseTriageAgent(Akgent[CaseTriageConfig, CaseTriageState]):
    cases: CaseRepository | None

    def on_start(self) -> None:
        self.state = CaseTriageState()
        self.cases = None
        self.state.observer(self)

    def set_case_repository(self, repository: CaseRepository) -> None:
        self.cases = repository


# composition root (src/main.py)
actor_system.proxy_tell(triage_addr, CaseTriageAgent).set_case_repository(DummyCaseRepository())
```

Interfaces in this repo are `typing.Protocol` (structural — implementations do not inherit) with
empty method bodies; `@runtime_checkable` only checks method *names*. See
`src/basic_akgents/case_repository.py`: `Case` (pydantic, `Field(frozen=True)` for the immutable
fields — `typing.ReadOnly` is 3.13 and `TypedDict`-only), `CaseNotFoundError`, the `CaseRepository`
protocol and the thread-safe `DummyCaseRepository` (seeded with `DEMO_CASES`: `case_1`-`case_3`
without a priority, `case_4`/`case_5` already prioritised).

One instance is shared by several agent threads, so implementations must be thread safe and should
hand out copies (`model_copy(deep=True)`); blocking I/O inside them blocks that agent's mailbox.

---

## 7. Human-in-the-loop

`UserProxy` bridges agents and humans:

- An agent sends a `UserMessage` to the proxy address to ask a question.
- `receiveMsg_UserMessage` just logs by default — **subclass it** to hook into a CLI/UI.
- The UI calls `process_human_input(content, original_message)`, which wraps the answer in a
  `ResultMessage` and sends it back to `message.sender`.

`CaseHandler` needs exactly this for its confirmation step.

### CLI variant used in this repo

`src/basic_akgents/cli_user_proxy.py` — `CliUserProxyAgent(UserProxy)`:

- `receiveMsg_UserMessage` prints the question, reads `input()` and calls `process_human_input(...)`.
- `receiveMsg_ResultMessage` only prints the final answer. Nothing is handed to this agent: the end of
  a case is announced as a `CaseClosed` event, which `CaseClosedSubscriber` puts on a queue the console
  loop waits on — so the `threading.Event` setter of the earlier version is gone.
- The proxy is a member of the team card (`case_team_card`, as its `entry_point`), which makes it a
  team member with telemetry and lets `TeamRuntime.process_human_input` route to it.
- **The proxy class is named in `case_team_card` itself, not passed in by a caller.** A `TeamCard` is
  the full description of a team, and `case_id` is the only thing that differs between two case teams;
  threading a `proxy_class` argument through `CaseRunner` and the console app only adds boilerplate to
  callers that have nothing to decide. A different front end writes its own card function instead.
- `input()` blocks the proxy's actor thread; acceptable for a console demo only.

End-to-end flow: `HandleCaseRequest` → coordinator sends `CaseTriageRequest` → triage answers with a
`CaseTriageResponse` (**proposed** priority + `reason`, nothing stored) → coordinator asks for approval
via `UserMessage` → proxy answers with `ResultMessage` → coordinator sends `CasePriorityDecision` →
triage persists and answers `CaseTriageCompleted` → coordinator reports the outcome as a
`ResultMessage` **to the proxy**, which closes the run.

Two shortcuts skip the human entirely, both signalled by flags on `CaseTriageResponse` and both ending
in a `ResultMessage` straight to the proxy: `known_case=False` (unknown case id) and
`already_prioritised=True` (see "Priorities" below).

### Ask the human to decide, not to do the work

The agents gather and reason; the human only approves. Two rules this repo follows:

- **Closed question with the reasoning attached.** The proposal carries a `reason`, and the answer is
  Enter/`y` (approve), `n` (reject) or a number 1-4 (override + approve in one step). Parsing lives in
  `CaseCoordinatorAgent._read_decision`.
- **No side effects before the verdict.** `receiveMsg_CaseTriageRequest` only computes;
  `receiveMsg_CasePriorityDecision` is the only handler that calls `save_case`. A rejection still logs
  an audit line but leaves the priority untouched.

The pending question is modelled in state (`status="awaiting_approval"`), not by blocking: the
coordinator returns immediately and its `receiveMsg_ResultMessage` ignores answers arriving outside
that window. Never `proxy_ask` the user proxy — it blocks the caller for as long as the human takes.

### Priorities: name the scale, and only triage what needs it

`src/basic_akgents/case_priority.py` holds `CasePriority(IntEnum)`: `UNSET=0`, `CRITICAL=1`, `HIGH=2`,
`NORMAL=3`, `LOW=4` — lower is more urgent. A bare `int` left "is 4 higher than 3?" unanswerable, so
the scale is named once and everything a human reads uses `priority.label` (`"3 - normal"`); the
approval prompt also prints `PRIORITY_SCALE`.

- `IntEnum` on purpose: it still compares and sorts as an int, pydantic accepts a plain `1` and
  serializes back to a number — needed because the value travels in `Message` fields and `BaseState`
  snapshots. Verified end-to-end through the framework's serializer.
- `TRIAGE_PRIORITIES` is the tuple a human may pick (everything except `UNSET`); `priority.is_set`
  answers "has this case been triaged".

**Only cases without a priority are triaged.** The guard sits in `CaseTriageAgent`, which owns the case
data: if `case.case_priority.is_set` it answers `CaseTriageResponse(already_prioritised=True, ...)`
without touching the store, and the coordinator closes the case with a "was not triaged" report instead
of asking for approval. A rejected proposal leaves the case at `UNSET`, so it is offered again on the
next run; an approval writes the priority and from then on the same guard refuses it.

---

## 8. Shutdown

- `agent.stop()` stops children blocking-first, then itself; `StopRecursively` triggers the same.
- The `Orchestrator` overrides `stop()` with a non-blocking drain (ADR-012).
- `ActorSystem.shutdown(timeout=120)` stops the context listener, stops every orchestrator
  concurrently with a grace period, then force-kills whatever remains in the pykka registry.
- Pykka guarantees the mailbox is fully drained before `on_stop` fires on a self-stop — subscriber
  ordering relies on this.

---

## 9. Gotchas checklist

1. Class-level `frozen=True` on a config breaks agent startup (`name`/`role` are written).
2. `frozen=True` on a **state** field is not enforced through `update_state`.
3. `ReadOnlyField` alone is documentation only — pair it with `frozen=True` if you mean it.
4. A handler returning `None` counts as "handled"; return `self.SUPER` to pass it on.
5. Unhandled message types only log a warning.
6. `update_state` never raises — it reports an `ErrorMessage` instead.
7. State mutations need an explicit `notify_state_change()` unless routed via `update_state`.
8. `createActor` propagates only `squad_id` from the parent config.
9. Do not annotate an agent as `Akgent[MyConfig, BaseState]` while assigning `MyState`.
10. `proxy_ask` is blocking — avoid it on paths that can loop back.
11. Never put an `ActorAddress` in a `BaseState` — keep addresses as instance attributes set in
    `on_start`, and store a member *name* in state if a snapshot needs the link.
12. `ActorSystem.createActor` attaches **no** orchestrator. Create an `Orchestrator` as the root actor
    and let it `createActor` the rest, otherwise `get_team()` / `get_team_member()` raise
    `WarningError("No orchestrator available ...")` and no telemetry is collected.
13. Repositories, clients and other live objects go on the instance via a setter called with
    `proxy_tell` — never in `config`/`state`, and `createActor` accepts no constructor arguments.
14. `typing.ReadOnly` is Python 3.13+ and `TypedDict`-only; on a pydantic model use
    `Field(frozen=True)` (importing it on 3.12 fails outright).

---

## 10. Where to read the source

`.venv/lib/python3.12/site-packages/akgentic/core/`

| File | Contents |
|---|---|
| `agent.py` | `Akgent` base class, dispatch, `createActor`, state helpers, proxies, `WarningError` |
| `agent_config.py` | `BaseConfig`, `ReadOnlyField` |
| `agent_state.py` | `BaseState`, `AkgentStateObserver`, `serializable_copy` |
| `orchestrator.py` | `Orchestrator`, `EventSubscriber`, `Timer`, team/metadata queries |
| `actor_system_impl.py` | `ActorSystem`, `ExecutionContext`, `Statistics`, shutdown |
| `user_proxy.py` | `UserProxy` |
| `agent_card.py` | `AgentCard` capability catalog |
| `actor_address.py`, `actor_address_impl.py` | `ActorAddress` and its impl/proxy/stopped variants |
| `messages/message.py` | `Message`, `UserMessage`, `ResultMessage`, `StopRecursively` |
| `messages/orchestrator.py` | Telemetry message types |
| `utils/serializer.py`, `utils/deserializer.py` | `SerializableBaseModel`, `deserialize_object` |
| `diagnostics/memory.py` | Memory diagnostics |

---

## 11. Conventions for this repo

- Follow the framework's own style: Google-style docstrings, `from __future__ import annotations`
  where needed, `X | None` unions, type hints everywhere.
- Keep the framework's `receiveMsg_<Type>` / `createActor` / `myAddress` camelCase names as-is
  (they are v1-compatibility API); use `snake_case` for your own code.
- One config class per agent, all inheriting a shared `CaseConfig`.
- One state class per agent, even when empty — makes later growth painless.
- Run things with `uv run`; add dependencies with `uv add` (dev tools with `uv add --dev`).
- The `Makefile` wraps the everyday commands: `make sync`, `make run CASE=case_2`, `make lint`,
  `make format`, `make check` (lint + format check, run it before committing), `make clean`.
- Quality gate is **ruff** only (dev-only dependency, configured in `pyproject.toml`): lint plus
  formatter, line length 100, `E501` off because the formatter owns wrapping, `N802` off because the
  framework's `receiveMsg_*` / `createActor` names are camelCase on purpose.

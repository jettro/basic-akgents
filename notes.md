# Learning about the akgents framework

## Start with the core
Before diving into all the goodies of the framework, I want to understand the basic concept of the agentic part of the system. 

There are examples in the project with extensive documentation. I'll work on my own example in this repository.

An important aspect of the framework is that a team of agents is lightweight. For our example, each team only handles one case. The team is archived when not actively used, but can we reactivated if the case requires it. The framework does not foresee long-running teams that you keep communicating with.

### Adding the dependency

```bash
# Add the dependency to the project
uv add akgentic-core
```

### Define the agents we need
- CaseCoordinator: Accepts the case and coordinates the complete handling of the case
- CaseTriage: Checks the case, tags it, prioritizes it
- CaseInformation: Facilitates fetching the context for the case
- CaseHandler: Handles the case by proposing changes to the system or writing aswers. Needs personal information and a confirmation by a person.
- GenericInforHandler: Handles cases asking for generic asnwers

We also need the HumanProxy

### Implementation notes

First we need to think about the state and the config

#### Config or state?

The rule I settled on: **config = facts that are fixed for the life of the agent, state = everything that changes while handling messages**.

The `case_id` therefore belongs in the config:

- The config is passed once into `Akgent.__init__` and the framework never replaces it. The state is *meant* to be replaced (`init_state`, `update_state`).
- The config is published once in the `StartMessage`, and `Orchestrator.get_team()` rebuilds the team roster from those messages. So the case id travels with the agent's identity and is still there when the team is reactivated - exactly what we need for the one-team-per-case model.
- The state on the other hand is snapshotted to the orchestrator on *every* change. An invariant sitting in there is pure noise.

Declaring it:

```python
class CaseConfig(BaseConfig):
    """Config shared by every agent working on a single case."""

    case_id: str = ReadOnlyField(frozen=True)
```

`ReadOnlyField` only marks the field `readOnly` in the JSON schema - it is a hint, not enforcement. Pydantic's `frozen=True` is what actually blocks assignment.

Two things I checked by running them:

1. **Do not freeze the whole model.** `Akgent.__init__` writes `self.config.name` and `self.config.role` when they are empty, so a class-level `ConfigDict(frozen=True)` blows up at startup. Per-field freezing is fine.
2. **Freezing a field in the state does not work.** `update_state` merges `{**self.state.model_dump(), **updates}` and rebuilds the object through `deserialize_object`. Because that constructs a *new* instance, `frozen=True` is never triggered and the value gets silently overwritten. The config has no such rebuild path.

#### Sharing the case id with the rest of the team

`createActor` only auto-propagates `squad_id`; every other config field has to be passed explicitly. Since all our agents work on the same case, a shared `CaseConfig` base plus an explicit hand-over is the cleanest:

```python
triage = self.createActor(
    CaseTriage,
    config=CaseTriageConfig(name="@CaseTriage", case_id=self.config.case_id),
)
```

Note: config lands in the persisted event stream via `StartMessage`, so no secrets in there. A case id is fine.

#### Connecting agents to each other

An `ActorAddress` is live runtime wiring, so it goes on the agent **instance**, never in the state.
Keep the state serializable.

Create the children in `on_start` and keep the addresses they return:

```python
class CaseCoordinator(Akgent[CaseCoordinatorConfig, CaseCoordinatorState]):
    def on_start(self) -> None:
        self.state = CaseCoordinatorState()
        self.state.observer(self)

        self.triage_agent: ActorAddress = self.createActor(
            CaseTriage,
            config=CaseTriageConfig(name="@CaseTriage", case_id=self.config.case_id),
        )
```

Do it in `on_start`, not in `__init__`: `__init__` runs in the caller's thread, while `on_start` and
every handler run in the actor's own thread, so those attributes need no locking.

When the agents are created *outside* the agent that has to talk to them, declare the slots in
`on_start` and let the assembler inject them afterwards with
`proxy_tell(coordinator, CaseCoordinator).set_agents(...)`:

```python
def on_start(self) -> None:
    ...
    self.information_agent: ActorAddress | None = None
    self.user_proxy: ActorAddress | None = None


def set_agents(self, information_agent: ActorAddress, user_proxy: ActorAddress) -> None:
    """Set references to other agents for routing."""
    self.information_agent = information_agent
    self.user_proxy = user_proxy
```

Other ways to get hold of an address:

- `self.get_team_member("@CaseTriage")` - looks the address up by name via the orchestrator.
- `self.myAddress` - our own address, e.g. as a reply-to.

If a snapshot really needs to record the link, store the **name** in the state
(`triage_agent_name: str | None`) and resolve it with `get_team_member` at the moment of use.

Talking to them once wired:

```python
self.send(self.triage_agent, CaseSubmitted(...))  # normal path, keeps thread + telemetry
```

And do not reach into these attributes from outside the actor
(`actor_ref._actor.triage_agent`) - always go through a message or `proxy_tell` / `proxy_ask`.

#### Starting the system: the orchestrator is not automatic

`ActorSystem.createActor` starts an agent **without** an orchestrator - it never creates one and never
passes one in. The agent then has `_orchestrator = None`, so `get_team()`, `get_team_member()` and
`notify_event()` raise `WarningError: No orchestrator available ...`, and no telemetry is recorded at
all.

The `Orchestrator` is just another `Akgent`; it becomes its own orchestrator in `on_start`
(`self._orchestrator = self.myAddress`). And `Akgent.createActor` is the only call that hands the
orchestrator address down (together with `team_id` and `parent`).

So the startup order is: orchestrator first, then let it create the root agent, then let that agent
create its own children.

```python
actor_system = ActorSystem()

orchestrator_addr = actor_system.createActor(
    Orchestrator, config=BaseConfig(name="@Orchestrator", role="Orchestrator")
)
orchestrator = actor_system.proxy_ask(orchestrator_addr, Orchestrator)

coordinator_addr = orchestrator.createActor(
    CaseCoordinatorAgent,
    config=CaseCoordinatorConfig(name="@CaseCoordinator", role="Coordinator", case_id=case_id),
)
```

Everything below that point inherits the orchestrator for free, and the telemetry queries
(`get_team()`, `get_messages()`, `get_states()`) are asked of the **orchestrator**, not of the
coordinator.

#### Talking to the human from the command line

`UserProxy` is the bridge to the human. Out of the box it only *logs* the question, so subclass it and
override `receiveMsg_UserMessage`. The reply goes back through `process_human_input(content, message)`,
which wraps the text in a `ResultMessage` and sends it to `message.sender` - the agent that asked.

```python
class CliUserProxyAgent(UserProxy):
    def receiveMsg_UserMessage(self, message: UserMessage, sender: ActorAddress) -> None:
        print(f"\n[{sender.name}] {message.content}")
        self.process_human_input(input("> ").strip(), message)

    def receiveMsg_ResultMessage(self, message: ResultMessage, sender: ActorAddress) -> None:
        print(f"\n[{sender.name}] {message.content}")
        self.completed.set()
```

The round trip for one case:

1. `main` reads the case id from the command line and starts orchestrator -> coordinator -> children.
2. `main` sends `HandleCaseRequest` to the coordinator.
3. The coordinator sends a `CaseTriageRequest` to `@CaseTriage` - no human involved yet.
4. Triage reads the case and answers with a `CaseTriageResponse`: the *proposed* priority plus the
   reason for it.
5. The coordinator sends a `UserMessage` to the proxy asking to approve that priority.
6. The proxy reads stdin and answers with a `ResultMessage` to the coordinator.
7. The coordinator turns the answer into a `CasePriorityDecision` for triage, which writes it to the
   case system and replies `CaseTriageCompleted`.
8. The coordinator sends the outcome as a `ResultMessage` to the **proxy**, which prints it. Done.

Two things worth remembering:

- `input()` runs in the proxy's own actor thread and blocks its mailbox while the human types. Fine for
  a console demo - other messages just queue up - but never do this in an agent that has to stay
  responsive.
- Don't `time.sleep()` in `main` hoping the workflow is finished. Hand the proxy a `threading.Event`
  and wait on it:

  ```python
  case_handled = threading.Event()
  actor_system.proxy_tell(user_proxy_address, CliUserProxyAgent).set_completion_event(case_handled)
  actor_system.tell(coordinator_addr, HandleCaseRequest(requester_id=getpass.getuser()))
  case_handled.wait(timeout=300)
  ```

  `proxy_tell` is a plain in-process method call, so the `Event` is passed by reference; it never goes
  through serialization the way a message field would. Mailbox order guarantees the event is set on the
  proxy before `HandleCaseRequest` can produce a result.

Create the proxy through the coordinator (`coordinator.createActor(CliUserProxyAgent, config=...)`) so
it is a real team member with telemetry, and keep its address in `set_agents` next to the other agents.

Run it with `uv run src/main.py case_1` (or without the argument, then it asks for the case id).

#### Ask the human to approve, not to do the work

First version asked the human "what can we do for you?" - but everything the team needs is already in
the case. The agents do the work, the human only *decides*: triage proposes a priority, the human
approves it. That is the human-in-the-loop pattern worth remembering.

Two rules that fell out of it:

- **Ask a closed question and show the reasoning.** The proposal carries a `reason` field
  ("the case mentions 'outage'"), so the human can judge in one glance instead of re-reading the case.
  Approve with Enter, reject with `n`, or type another priority (1-4) to override in one step.
- **Do not persist before the verdict.** `receiveMsg_CaseTriageRequest` only *computes* the priority;
  `receiveMsg_CasePriorityDecision` is the only handler that calls `save_case`. Approval stores the
  priority plus `"priority 2 approved by <user>"`, rejection leaves the priority alone and logs
  `"proposed priority 1 rejected by <user>"` - the refusal itself is worth keeping.

The waiting is in the *state*, not in a blocked thread: the coordinator sets `status =
"awaiting_approval"` and returns. Its `receiveMsg_ResultMessage` checks that status and ignores
anything arriving outside that window, which is how an actor models "a question is open" without
holding on to a thread. Never `proxy_ask` the proxy for the answer - that blocks the coordinator's
mailbox for as long as the human takes.

An unknown case id now ends the run right away (`known_case=False` -> "closed - Case ... is not known"),
because without a case there is nothing to triage and nothing to approve.

#### Giving an agent a repository (or any other dependency)

Interface first. In Python "interface style" means a `typing.Protocol`: structural typing, so an
implementation does **not** inherit from it, it only has to have the same methods. Leave the bodies
empty (`...`) - a Protocol method with a real body silently becomes a default implementation for
anything that *does* inherit from it.

```python
@runtime_checkable
class CaseRepository(Protocol):
    def load_case(self, case_id: str) -> Case: ...
    def save_case(self, case: Case) -> None: ...


class DummyCaseRepository:  # no inheritance needed
    def load_case(self, case_id: str) -> Case: ...
    def save_case(self, case: Case) -> None: ...
```

`@runtime_checkable` only enables `isinstance()`, and only checks *method names*, never signatures.
Type checking of the real contract happens at the injection point (`case_repository: CaseRepository =
DummyCaseRepository()`). Use an `ABC` instead only when you want shared implementation or a hard
"must inherit" rule.

Data goes in a plain `pydantic.BaseModel`. Note: `typing.ReadOnly` does **not** work here - it only
exists from Python 3.13 and only for `TypedDict`. For a model field it is `Field(frozen=True)`.

```python
class Case(BaseModel):
    case_id: str = Field(frozen=True)
    case_description: str = Field(default="", frozen=True)
    case_priority: CasePriority = CasePriority.UNSET
    actions: list[str] = Field(default_factory=list)
```

Frozen fields also mean you never edit a case in place; produce a new one:
`case.model_copy(update={"case_priority": CasePriority.CRITICAL})`.

Getting it into the agent - the same rule as with an `ActorAddress`: **a repository is a live object,
so it belongs on the instance, never in the config or the state** (both get serialized and snapshotted
to the orchestrator). And `createActor(actor_class, agent_id=..., config=...)` takes no extra
constructor arguments, so it cannot go in there either. That leaves the setter, exactly like
`set_agents`:

```python
class CaseTriageAgent(Akgent[CaseTriageConfig, CaseTriageState]):
    cases: CaseRepository | None

    def on_start(self) -> None:
        self.state = CaseTriageState()
        self.cases = None
        self.state.observer(self)

    def set_case_repository(self, repository: CaseRepository) -> None:
        self.cases = repository
```

```python
# main.py - the composition root decides which implementation the team gets
case_repository: CaseRepository = DummyCaseRepository()
actor_system.proxy_tell(triage_agent_address, CaseTriageAgent).set_case_repository(case_repository)
```

`proxy_tell` is a normal in-process method call, so the object is passed by reference. Mailbox order
guarantees the setter runs before the first `CaseTriageRequest` arrives.

Two consequences of the actor model:

- One repository instance is shared by several agent **threads**, so the implementation must be thread
  safe. `DummyCaseRepository` guards its dict with a `threading.Lock` and hands out
  `model_copy(deep=True)` copies, so a caller can never mutate the store by accident.
- Blocking I/O in a repository blocks that agent's mailbox. Fine for an in-memory dummy, something to
  watch with a real database.

If a whole tree of agents needs the same dependency, a setter on every one of them gets tedious. The
alternative is a tiny provider module (`case_repository()` returning a module-level singleton that the
composition root replaces once) which each `on_start` calls itself. Explicit injection stays the
better default: it is visible and trivially replaceable in a test.

> The setter itself survived, the *owner* did not: the repository now lives in one dedicated agent.
> See "Give the shared state an owner" below.

#### Name the scale: is 4 higher than 3?

Honest answer to my own question: **no, a bare number says nothing.** `case_priority: int = 4` forced
every reader to guess whether 4 was "very urgent" or "whenever". Two conventions exist and both are
common - ITIL/Jira count *down* (P1 is the emergency), a plain "importance" score counts *up*. If the
code does not say which, the human at the prompt has to guess.

So the scale moved into `case_priority.py` as an `IntEnum`:

```python
class CasePriority(IntEnum):
    UNSET = 0
    CRITICAL = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
```

Why an `IntEnum` and not a `StrEnum` or a plain constant:

- It still *is* an int, so `CasePriority.CRITICAL < CasePriority.LOW` sorts correctly, existing
  comparisons keep working and pydantic serializes it as a number - important, because these values
  travel through `Message` fields and `BaseState` snapshots.
- The member name carries the meaning: `1 - critical` instead of `1`.
- `int` -> enum conversion is automatic in pydantic, so `Case(case_priority=1)` and a deserialized
  telemetry snapshot both come back as `CasePriority.CRITICAL`.

Everything a human reads goes through `.label` (`"3 - normal"`), and the prompt now prints the whole
scale (`PRIORITY_SCALE`) so nobody has to remember the direction. The lesson is general: **a magic
number that a human must interpret needs a name, and the legend belongs next to the question.**

#### Only triage what still needs triaging

`UNSET = 0` gives "not looked at yet" a value of its own, instead of abusing the lowest priority for
it. That turns the guard into one readable line in `receiveMsg_CaseTriageRequest`:

```python
if case.case_priority.is_set:
    ...  # answer with already_prioritised=True, do not touch the case
```

The check lives in **triage**, not in the coordinator: triage owns the case data, so it decides whether
there is work. The coordinator only reacts to the flag - `already_prioritised` closes the case with a
report and never asks the human anything (15 messages instead of 27, so the shortcut is visible in the
telemetry too).

Three flags now describe the outcome of one request, which is worth keeping apart:

| `known_case` | `already_prioritised` | what happens |
|---|---|---|
| `False` | - | case id unknown, run closes |
| `True` | `True` | priority was already decided, nothing to do |
| `True` | `False` | proposal goes to the human for approval |

A rejected proposal leaves the case at `UNSET`, so it is picked up again on the next run - a rejection
is "not this priority", not "never triage this". An approval writes the priority and the audit line, and
from then on the case is refused by the same guard.

The dummy store holds five cases on purpose: `case_1`, `case_2` and `case_3` without a priority,
`case_4` (critical) and `case_5` (low) already decided.

```
uv run src/main.py case_1     # no priority -> proposes 3 - normal
uv run src/main.py case_2     # no priority -> proposes 1 - critical (mentions 'urgent')
uv run src/main.py case_4     # already 1 - critical -> "was not triaged"
uv run src/main.py case_42    # unknown -> closed
uv run src/main.py            # no argument -> lists the store, then asks for the id
```

#### Give the shared state an owner: `@CaseRepository`

The question that started this: one repository instance shared by several agent **threads** needs a
lock, and a lock is a smell in an actor system. Two things pushed me over:

- `akgentic/core` does not contain a single lock. Its own pile of shared mutable state - message
  history, state snapshots, metadata - is the `Orchestrator`, and that is *an actor*. The framework's
  answer to shared state is "give it an owner", not "guard it".
- The lock made every *call* atomic, not the *sequence*. Triage did load -> `model_copy` -> `save_case`,
  so a second writer (`CaseHandler` is coming) could slip in between the load and the save and its
  appended action would silently vanish. A lock inside the repository can never fix that; only the
  caller knows where the transaction begins.

So the store moved behind one agent - `CaseRepositoryAgent` in `case_repository_agent.py` - and the
case data became a conversation:

```python
class CaseInformationRequest(Message):
    case_id: str = ""  # empty means "the case of this team"


class CaseInformationResponse(Message):
    case_id: str = ""
    found: bool = False
    case: Case | None = None  # the whole case travels along
```

A `Case` is a plain `pydantic.BaseModel`, so it may sit inside a `Message`: the serializer turns a
nested model into its `model_dump()` and the `__model__` marker of the *message* is enough to rebuild
the whole thing (checked with a `model_dump()` / `deserialize_object()` round trip). Note the
difference with an `ActorAddress` or a repository: data is fine in a message, a live object is not.

Writes got their own pair, and that is where the payoff is:

```python
class CaseUpdateRequest(Message):
    case_id: str = ""
    case_priority: CasePriority = CasePriority.UNSET  # UNSET: leave the priority alone
    action: str = ""  # line for the audit log
```

The request describes the **intent**, not the result, so load -> change -> save happens inside a single
handler of a single-threaded agent. That is atomic by construction, and `DummyCaseRepository` could
throw its `threading.Lock` away. `UNSET` doubles as "do not touch the priority", which is exactly what
a rejection needs: the refusal is logged, the priority stays where it was.

**What it costs: reading is no longer a function call.** Triage cannot say `case = self.cases.load_case(...)`
anymore, so every handler that needed the case had to be cut in two:

```
CaseTriageRequest    -> CaseInformationRequest  ..  CaseInformationResponse -> CaseTriageResponse
CasePriorityDecision -> CaseUpdateRequest       ..  CaseUpdateResponse      -> CaseTriageCompleted
```

Which means triage now has to remember what it was doing, and that is a `status` in its state
(`loading`, `proposed`, `storing`, ...) plus a guard at the top of each answer handler:

```python
if self.state.status != "loading":
    return  # no request of ours is open, this answer is not ours to act on
```

Same trick as the coordinator's `awaiting_approval`: **an actor waits in its state, never in its
thread.** The tempting shortcut is `proxy_ask(repository, CaseRepositoryAgent).load_case(...)` - one
line, no state machine - but that blocks the triage thread and its whole mailbox until the repository
answers. It also gives up the telemetry, because `proxy_ask` bypasses `_receiveMessage`.

Two smaller lessons:

- The address of the requester goes on the *instance* (`self.reply_to = sender` in the request handler),
  not in the state - an `ActorAddress` is not serializable. Everything the second half of the handler
  still needs from the first half (`requester_id`, `proposed_priority`, `approved`) *is* in the state.
- The repository agent keeps `reads` and `writes` counters in its state. Not needed for the logic, but
  now the orchestrator shows how often the store was touched, which the shared object never did:
  `proxy_tell` calls produce no telemetry at all.

The price in messages is visible in the summary: a full run went from 27 to 40 messages, the
"already prioritised" shortcut from 15 to 22. That is the cost of making every case access an
observable event - and worth it the moment a second agent starts writing.

#### A console that can look around, not only ask for a case

The prompt used to have one question ("case id?"), which meant everything the framework keeps around
a team was invisible. It now has a small verb per thing to look at: `cases` for the store, `teams` for
the event store, `team` for one of them in full, `events` for its stored stream, `feed` for what is
happening now, `resume` to put a stopped team back to work. An unknown verb is still read as a case id,
so the old habit of typing `case_1` costs nothing.

Two things this made obvious:

- **A stopped team is a readable team.** `Process` keeps the card it was created from, so the structure
  of a team can be printed months later, and the store keeps the event stream plus one state snapshot
  per agent next to it. Nothing has to be alive for a UI to describe a team - and `resume_team` builds
  the same team back out of exactly that, replaying the history *as history*: subscribers see it,
  agents do not, so nobody is asked the old questions again.
- **The console layer is where a "second panel" problem lives, not the framework.** A subscriber sees
  every message of every team (`EventTap`), and one terminal cannot show a stream and a prompt at the
  same time. So the tap only *transports* - a `queue.Queue`, like `CaseClosedSubscriber` - and the
  console offers three ways to look: a tail afterwards (`feed`), an echo while it happens (`follow`),
  and one line per message appended to `data/live-feed.log`, which `tail -f` in a second terminal turns
  into the panel of its own. No TUI, no dependency.

The two reading commands walked straight into a bug the demo had been hiding: the stored event stream was
written in a form the store cannot read back, because `Case` was a plain pydantic model travelling
inside a message, and pydantic's `model_dump()` keeps a `CasePriority` where the framework's own
serializer would have written the number. Nothing noticed as long as nobody read the events; `events`
and `resume` did. Gotchas 20-25 in `notes_team.md` have the details, including the `@cache` trap that
had the console reading a second, empty case store.

#### Colour, and the one place it is allowed to live

The console does a lot of printing now, and a wall of grey text hides exactly what one wants to see:
which priority, which team, which of the forty messages is the conversation instead of telemetry. So
[rich](https://rich.readthedocs.io) came in - the only dependency in this repo that is there for
presentation - and with it tables for the listings, a tree for the shape of a team, a panel around a
question and around a result, and one colour per kind of message.

Three decisions were worth more than the colours themselves:

- **Name what a thing is, not how it looks.** `basic_akgents/terminal.py` holds one `Theme` with
  semantic keys - `heading`, `priority.critical`, `status.stopped`, `msg.telemetry` - and nothing
  outside it ever writes "red". Repainting the demo is one edit in that dictionary, and the printers
  keep reading as prose: `Text(priority.label, style=_priority_style(priority))`.
- **The terminal is not part of the front end.** `CliUserProxyAgent` is an agent, and agent code may
  not import `basic_akgents.cli` - ruff's banned-api rule enforces that, so the console can be swapped
  for a web UI. But the proxy is the one agent that has to talk to the same terminal. Hence
  `terminal.py` *next to* the agents: the shared console instance and two helpers (`say`, `ask`), no
  layout, no domain knowledge. The front end imports it, the proxy imports it, neither imports the
  other.
- **Keep a plain copy of everything.** `render_event` returns a `rich.Text`, which carries the styling
  *and* the bare string: `data/live-feed.log` gets `text.plain`, so `tail -f` in the second terminal
  shows lines and not escape codes. Rich itself takes care of the other direction - it drops the colour
  when stdout is not a terminal, and honours `NO_COLOR` - so piping the demo into a file still gives
  readable text.

Two rich lessons, both found by running it:

- `Text.rstrip()` is not `str.rstrip()`: it edits in place and returns `None`. Returning its result
  handed a `None` to the feed thread, which only showed up as an `AttributeError` in a background
  thread - the run itself carried on.
- A table is the wrong shape for a very wide column. The rendered message line asks for ~150
  characters, and rich pays for that by shrinking the neighbours: the sequence number and the clock
  collapsed into an ellipsis, whatever `min_width` or `width` they were given. The event stream is now
  printed as one soft wrapped line per event, which leaves the wrapping to the terminal; tables stayed
  where the content is short and column widths mean something.

> Wider notes on the framework (dispatch, telemetry, lifecycle, gotchas) live in `.junie/guidelines.md`.
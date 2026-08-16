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
self.send(self.triage_agent, CaseSubmitted(...))   # normal path, keeps thread + telemetry
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

> Wider notes on the framework (dispatch, telemetry, lifecycle, gotchas) live in `.junie/guidelines.md`.
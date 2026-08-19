# Working in teams

Reference to module: https://github.com/b12consulting/akgentic-team

## Generic remarks

Just like in real life, it is important to be able to work in teams. This means that you need to be able to communicate effectively with your teammates, and to be able to work together towards a common goal. 

We have seen how to group agents and build a tree of agents using the coordinator and by instantiating new agents from existing agents. We did not see how to manage the lifecycle of teams yet. We want to archive teams, revive teams, and repair broken downs teams.

The Akgents framework has a teams module that provides the tools to manage the lifecycle of teams. In this blog post, I will explore how to use the Akgentic teams module to manage the lifecycle of teams. I will adapt the sample from the previous post in this series of blogs about the Akgentic framework.

## Different parts of the teams module

TeamCard -> Describes the team with all the members and their roles and relationships.

ActorSystem -> The actor system is the central component of the Akgentic framework. It is responsible for managing the lifecycle of agents and teams. It is also responsible for managing the communication between agents and teams.

TeamManager -> The team manager is responsible for managing the lifecycle of teams. It is responsible for creating, archiving, reviving, and repairing teams.

## One case -> One Team -> One case
A team is created for a single case and stopped again as soon as that case is done, which is what teams in this framework are for.

A stopped team is not gone: its card, its metadata, its events and the last state of every agent stay in the event store. That makes this class the reading side as well - `list_teams`, `load_events`, `load_agent_states` - and `resume_case` puts such a team back together and gives it work again.

## The event store

You need to know the basics about the event store to understand how teams work. The event store is a database that stores all the events that happen in the system. The event store is used by the team manager to manage the lifecycle of teams. The event store is also used by the team manager to manage the communication between agents and teams.

Akgents teams comes with multiple event store implementations. For testing and development, you can use the file based  `YamlEventStore`. Due to its format, you can easily inspect the events and the state of the agents. I leave it to you to explore the event store and the state of the agents.

## The team manager and the teams

The team manager is the central component of the teams module. It is responsible for creating, managing and stopping teams. The team manager is also responsible for managing the communication between agents and teams. In the sample I created the the `CaseRunner`. This contains the initialization of the `TeamManager` and working with teams. 

```python
from akgentic.team import TeamManager, YamlEventStore
from akgentic.core import ActorSystem

TeamManager(
    actor_system=ActorSystem(),
    event_store=YamlEventStore(event_store_dir),
    # Shared by every team of this run, so they route on team_id.
    subscribers=[CaseClosedSubscriber(self._closed), *subscribers],
)
```

To create a team for a specific case, we use the `run_case` method. That method produces a `TeamRuntime` object that we can use to interact with the team. The team is kicked-off uby sending a `HandleCaseRequest` message through the runtime. 

```python
# Part of the run_case method, the construction of the team
runtime = self._manager.create_team(
    team_card=case_team_card(),
    user_id=requester_id,
    metadata=CaseMetaData(case_id=case_id),
)

# Send the kickoff message to the team
runtime.send(HandleCaseRequest(requester_id=requester_id))
```

Notice that the kickoff message does not contain the `case_id`. This is because the `case_id` is part of the metadata of the team.  

## Installation

```bash
# Install the teams module
uv add akgentic-team

# Install the CLI that we can use to work with the teams
uv add "akgentic-team[cli]"
```

## Pinning down the case_id for a team
We used to configure the case_id as a static parameters in the config class of the Agents. This works, but it does not fit the phylosophy of the framework. When working with teams, the agents are constructed based on a TeamCard. This TeamCard can be read from a yaml file. So, the TeamCard is static, and as you will see later on, the TeamCard contains the Agents and all the Agent configuration. Therefore, the framework provides a different mechanism to provide fixed values to the team at Runtime. Akgents teams comes with typed metadata. When starting the team using a team card, you also provide the team metadata. Through the metadata we can pass the case_id. Each Akgent has access to the team metadata through the link with the coordinator.

I want you to have a look at the `TeamCard` class first. Notice how we configure the human proxy `AgentCard` as the entry point. The message type to start the team is the `HandleCaseRequest` message. 

```python
# Create a TeamCard using existing AgentCard instances
from akgentic.team import TeamCard, TeamCardMember

TeamCard(
        name="case-handling-team",
        description="Handles cases when requested using an id.",
        entry_point=TeamCardMember(card=human_proxy_card),
        members=[
            TeamCardMember(
                card=coordinator_card, members=[
                    TeamCardMember(card=triage_agent_card),
                    TeamCardMember(card=repository_agent_card)
                ]
            ),
        ],
        message_types=[HandleCaseRequest],
        metadata_type=CaseMetaData,
        welcome_message=f"Case team ready to handle your case.",
    )
```

Did you notice how we configured the metadata type. I like it that this is a serializable object. Next is the definition of the class for the metadata.

```python
from akgentic.team import TeamMetadata
from pydantic import Field

class CaseMetaData(TeamMetadata):
    case_id: str = Field(json_schema_extra={"indexed": True})
```

Each agent can use the link to the team through the coordinator to access the metadata.

```python
from typing import Any

from akgentic.core import ActorAddress, Akgent
from akgentic.core.agent import WarningError

def find_team_case_id(agent: Akgent[Any, Any]) -> str:
    """Look up the case ID of the team.

    Args:
        agent: Agent doing the lookup.

    Returns:
        Case ID of the team.
    """

    case_metadata: CaseMetaData = agent.orchestrator_proxy_ask.get_metadata()
    if not isinstance(case_metadata, CaseMetaData) or case_metadata.case_id is None:
        raise WarningError(f"No case metadata and case_id in the team of {agent.config.name}.")
    return case_metadata.case_id
```

## Handing over the CaseRepository to the CaseRepositoryAgent

In my Java life, I got used to Dependency Injection when writing applications. Therefore, I started this project by ingecting the `DummyCaseRepository` into the `CaseRepositoryAgent` after initialization of the agent. When creating an Akgent through an AgentCard, this is not the right way forward. Therefore, I switched to a Python functionality through an akgentic util to create an instance of a specified class. 

The AgentCard for the CaseRepositoryAgent looks like this.

```python
from akgentic.core import AgentCard

AgentCard(
        description="Access cases through a repository.",
        skills=["repository"],
        agent_class=CaseRepositoryAgent,
        config=CaseRepositoryConfig(
            name="@CaseRepository",
            role="Repository",
            backend="basic_akgents.case_repository.DummyCaseRepository",
        ),
    )
```

In the `case_repository.py` file, the `DummyCaseRepository` class is defined. This class is used as the default backend for the `CaseRepositoryAgent` and provides a basic implementation of the `CaseRepository` interface. The agent gets an instance of this repository through this method call.

```python
from functools import cache
from akgentic.core.utils import import_class

@cache
def _case_repository(backend: str) -> CaseRepository:
    """Build the backend named by a dotted path, once per path.

    Args:
        backend: Fully qualified path of a `CaseRepository` implementation.

    Returns:
        The backend to work with.

    Raises:
        TypeError: If the resolved class is not a `CaseRepository`.
    """
    repository = import_class(backend)()

    if not isinstance(repository, CaseRepository):
        raise TypeError(f"{backend!r} does not implement CaseRepository")

    return repository

```

## Gotchas

1.
TeamCard.metadata is team-scoped: Process.metadata + Orchestrator.set_metadata(). Agents get it only via self.orchestrator_proxy_ask.get_metadata(), and not during on_start — the push happens after TeamFactory.build.
2.
metadata_type must be declared on the card, or create_team(metadata=...) raises ValueError; only TeamMetadata subclasses produce metadata_indexes, and only fields marked json_schema_extra={"indexed": True} are filterable (scalars only — no float).
3.
supervisor_addrs = first layer of members only. Entry point excluded, deeper members excluded. runtime.send() needs at least one member; message_types[0] is what a plain str is wrapped in.
4.
Children are spawned through the parent's mailbox → a parent's on_start can never see its children. Resolve team members lazily.
5.
AgentCard: description required, config.role required and non-empty, config.name unique in the tree, entry_point.headcount == 1, headcount > 1 renames instances to @Name_0, @Name_1.
6.
ServiceRegistry / NullServiceRegistry is multi-worker service discovery, not dependency injection. Live objects: proxy_tell setters over runtime.addrs, repeated after every resume_team.
7.
process_human_input() on TeamRuntime only routes to an agent whose card class is a UserProxy subclass — so the human bridge must be in the card tree.
8.
TeamManager always installs PersistenceSubscriber (and a TimerStopSubscriber) per team; pass extra ones via the constructor's subscribers= for shared ones.
9.
Call manager.stop_team(runtime.id) before actor_system.shutdown() — otherwise the Process stays RUNNING and resume_team refuses it.
10.
Two kinds of "live object", and only one of them is wiring: replaceable infrastructure (repository, HTTP client, LLM client) is named in the config and built by the agent in on_start; a callback into the host process (threading.Event, queue, UI handle) has to be handed over with a proxy_tell setter. Gotcha 6 only applies to the second kind — that is the only thing to re-inject after resume_team.
11.
An address of a colleague is not a live object either: get_team_member("@Name") reads it from the roster of the orchestrator. Wrapping that in a functools.cached_property gives a lazy lookup on the first message, cached for the rest of the run, and removes every `| None` guard from the agent.
12.
cached_property is safe on an Akgent: pykka introspects attributes straight from the merged class/instance __dict__ (_introspection.get_attr_from_parent) and akgentic's proxy_tell hands back its own ProxyWrapper, so nothing ever evaluates the property from another thread. It caches for the life of the agent, so only use it for members that outlive it.
13.
Keep the member names in one module (case_team.py) and use them both for the cards in main and for the lookups in the agents — a typo then fails at import instead of as a WarningError halfway through a case.
14.
notify_event(obj) → EventMessage(event=obj) → Orchestrator.receiveMsg_EventMessage → every subscriber, and it is persisted like any other event. That is the supported way for a team to talk to the outside world; the payload is a frozen dataclass in a stable module (case_events.CaseClosed), because the serializer writes its import path into the stored event.
15.
on_message runs on the actor thread of the orchestrator that published the event. Never call stop_team/resume_team for that team from inside it — put the signal on a queue.Queue and let the owning thread act, the way TimerStopSubscriber offloads to a daemon thread.
16.
A subscriber passed to TeamManager(subscribers=[...]) is shared by every team of that manager: it must be thread safe and it must route on msg.team_id instead of asserting it (the per-team PersistenceSubscriber asserts precisely because it is not shared).
17.
resume_team replays history through the subscribers, so a reacting subscriber has to honour set_restoring(team_id, restoring) or it acts twice on the same case.
18.
runtime.id == team_id, and stop_team waits for the full drain — which doubles as the barrier that keeps the last console output of a team out of the next prompt. Stop the old team before creating the next one, or two @UserProxy actors compete for stdin.
19.
With a domain event as the completion signal the threading.Event setter disappears: a created and a resumed team now need no post-create wiring at all. main creates one team per case in a loop, waits on the queue filtered by team_id, and decides itself whether the next case follows or the CLI closes.
20.
Anything that travels inside a message must be a SerializableBaseModel, never a plain pydantic BaseModel. YamlEventStore dumps with yaml.Dumper (which happily writes python/object tags) and reads with safe_load, so a value it cannot read back makes the *whole* events.yaml unreadable: load_events() returns [] and resume_team dies with "No Orchestrator StartMessage found". The framework's serialize() walks a SerializableBaseModel field by field and turns an IntEnum into a plain number; pydantic's own model_dump() keeps the enum object. `Case` was a BaseModel and cost exactly this.
21.
The reading side of a team is the EventStore, not the TeamManager: list_teams(user_id=, status=, metadata=), load_team, load_events, load_agent_states, get_max_sequence. The manager only creates, gets, resumes, stops, deletes and updates metadata — so keep the store instance you pass in if you want to list teams. list_teams returns DELETED ones too unless you filter on status.
22.
A stopped team can be described in full without any actor being alive: Process carries the team_card (so the structure is there), the metadata plus its flattened metadata_indexes, the status, the owner and the timestamps, and the store has the events and one state snapshot per agent next to it.
23.
resume_team replays into the orchestrator and the subscribers, not into the agent handlers: state snapshots are pushed back with init_state and the history is restored as history, so a resumed team does not repeat its conversation and the human is not asked the old questions again. Hand it a fresh message to make it work. The message count starts at what it was (43 -> 67 for a second run), because the replayed history counts.
24.
StateChangedMessage never reaches events.yaml: the PersistenceSubscriber turns it into an AgentStateSnapshot, one per agent, overwritten. A live tap on on_message sees every state change, the stored stream only what was sent, received, processed and notified — worth knowing before comparing the two.
25.
Not a team thing but it bit here anyway: @cache keys on the call, not on the resolved arguments. build_case_repository() and build_case_repository(DEFAULT_CASE_REPOSITORY) are two cache entries and therefore two stores — the console then reads a store no agent ever writes to. Put the cache on a private function that has no default.
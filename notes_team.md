# Working in teams

## Generic remarks

Just like in real life, it is important to be able to work in teams. This means that you need to be able to communicate effectively with your teammates, and to be able to work together towards a common goal. 

We have seen how to group agents and build a tree of agents using the coordinator and by instantiating new agents from existing agents. We did not see how to manage the lifecycle of teams yet. We want to archive teams, revive teams, and repair broken downs teams.

The Akgents framework has a teams module that provides the tools to manage the lifecycle of teams. 

## Different parts of the teams module

TeamCard -> Initialise the 

## Installation

```bash
# Install the teams module
uv add akgentic-team

# Install the CLI that we can use to work with the teams
uv add "akgentic-team[cli]"
```

## Pinning down the case_id for a team
We used to configure the case_id as a static parameters in the config class of the Agents. Now, when working with the teams, there is a metadata module to use for this purpose.



## Create the team definition



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
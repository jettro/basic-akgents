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
from akgentic.core import ActorAddress, Akgent, BaseState
from akgentic.core.messages import Message

from basic_akgents.case_model import CaseConfig
from basic_akgents.case_triage import CaseTriageRequest, CaseTriageResponse


class HandleCaseRequest(Message):
    requester_id:str = ""

class CaseCoordinatorState(BaseState):
    status: str = "new"

class CaseCoordinatorConfig(CaseConfig):
    pass

class CaseCoordinatorAgent(Akgent[CaseCoordinatorConfig, CaseCoordinatorState]):
    triage_agent: ActorAddress | None

    def on_start(self) -> None:
        """Initialize the case coordinator."""
        self.state = CaseCoordinatorState() # Initialize the first state object

        # Live wiring to the other agents: instance attributes, never state.
        self.triage_agent = None

        self.state.observer(self)


    def set_agents(self,
                   triage_agent_address: ActorAddress):
        self.triage_agent = triage_agent_address

    def receiveMsg_HandleCaseRequest(self, message: HandleCaseRequest, sender: ActorAddress) -> None:

        # Route to triage agent
        if self.triage_agent is not None:
            self.send(
                self.triage_agent,
                CaseTriageRequest(),
            )

    def receiveMsg_CaseTriageResponse(self, message: CaseTriageResponse, sender: ActorAddress) -> None:
        print(message.case_description)

from akgentic.core import Akgent, BaseState, ActorAddress
from akgentic.core.messages import Message

from basic_akgents.case_model import CaseConfig

class CaseTriageRequest(Message):
    pass

class CaseTriageResponse(Message):
    case_description:str
    case_sender: str
    case_priority: int = 4

class CaseTriageConfig(CaseConfig):
    pass

class CaseTriageState(BaseState):
    pass

class CaseTriageAgent(Akgent[CaseTriageConfig, CaseTriageState]):

    def on_start(self) -> None:
        self.state = CaseTriageState()
        self.state.observer(self)

    def receiveMsg_CaseTriageRequest(self, message: CaseTriageRequest, sender: ActorAddress) -> None:
        case_id = self.config.case_id

        # Lookup case details

        # Determine the priority of the request
        case_priority = 2

        response = CaseTriageResponse(
            case_description="Just another case",
            case_sender="Noob",
            case_priority=case_priority
        )

        self.send(sender, response)

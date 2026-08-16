from akgentic.core import BaseConfig
from akgentic.core.agent_config import ReadOnlyField


class CaseConfig(BaseConfig):
    """Config shared by every agent working on a single case."""
    case_id: str = ReadOnlyField(frozen=True)


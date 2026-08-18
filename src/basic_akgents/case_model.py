from akgentic.core import BaseConfig
from akgentic.core.agent_config import ReadOnlyField
from akgentic.team import TeamMetadata
from pydantic import Field


class CaseConfig(BaseConfig):
    """Config shared by every agent working on a single case."""

    case_id: str = ReadOnlyField(frozen=True)


class CaseMetaData(TeamMetadata):
    case_id: str = Field(json_schema_extra={"indexed": True})

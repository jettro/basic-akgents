from akgentic.team import Process, TeamMetadata
from pydantic import Field

class CaseMetaData(TeamMetadata):
    case_id: str = Field(json_schema_extra={"indexed": True})


def case_id_of(process: Process) -> str:
    """Read the case a stored team was created for.

    The metadata is what a stored team can be found by, so it is also the answer
    to "which case is this team about" once the actors are long gone.

    Args:
        process: Team as the event store holds it.

    Returns:
        The case id, or an empty string for a team without case metadata.
    """
    metadata = process.metadata

    return metadata.case_id if isinstance(metadata, CaseMetaData) else ""

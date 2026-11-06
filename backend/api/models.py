"""Request-model pieces shared by more than one route module."""

from pydantic import BaseModel, Field


class ApprovalTicketModel(BaseModel):
    """A signed approval minted by the Electron main process after the person
    tapped (see backend/services/approvals.py). Extra fields are refused, and the
    sizes are bounded before the signature is even looked at."""

    model_config = {"extra": "forbid"}
    payload: str = Field(..., max_length=4096)
    sig: str = Field(..., min_length=64, max_length=64)

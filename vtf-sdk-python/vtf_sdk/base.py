"""Base model for all vtf SDK types."""
from pydantic import BaseModel, ConfigDict


class VtfModel(BaseModel):
    """Base for all vtf SDK models. Frozen (immutable) and forward-compatible."""

    model_config = ConfigDict(frozen=True, extra="ignore")

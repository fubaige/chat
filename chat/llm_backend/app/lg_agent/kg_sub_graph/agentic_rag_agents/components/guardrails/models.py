from typing import Literal, Optional
from pydantic import BaseModel, Field


class GuardrailsOutput(BaseModel):
    decision: Literal["end", "planner"] = Field(
        description="Decision on whether the question is related to the graph contents or knowledge base."
    )
    response: Optional[str] = Field(
        default=None,
        description="A polite and reasonable response to the user if the decision is 'end'. If 'planner', this can be empty."
    )

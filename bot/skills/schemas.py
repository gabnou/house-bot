from pydantic import BaseModel
from typing import Optional, Any, Dict


class ToolInput(BaseModel):
    """Base input for skills - extend per tool."""
    pass


class ToolOutput(BaseModel):
    ok: bool = True
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

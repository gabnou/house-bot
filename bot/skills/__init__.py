"""Skills package: registry and helpers for agentic skills."""
from .registry import register, get, list_tools
from .utils import format_tool_reply
# Import modules that register skills on import
from . import shopping  # registers shopping tools
from . import weather   # registers weather tools
from . import calendar  # registers calendar tools

from typing import Callable, Any, Dict, Optional

_registry: Dict[str, Dict[str, Any]] = {}
_prompt_registry: Dict[str, Callable[[], str]] = {}


def register(name: str, fn: Callable, input_schema=None, output_schema=None, desc: str = ""):
    """Register a skill/tool.

    name: canonical skill name (e.g. "shopping.add")
    fn: callable accepting a dict or Pydantic model
    input_schema/output_schema: optional Pydantic models
    desc: short description
    """
    _registry[name] = {
        "fn": fn,
        "in": input_schema,
        "out": output_schema,
        "desc": desc,
    }


def register_prompt(category: str, fn: Callable[[], str]):
    """Register the LLM prompt builder for a category (e.g. "shopping")."""
    _prompt_registry[category] = fn


def get_prompt(category: str) -> Optional[Callable[[], str]]:
    """Return the prompt builder callable for the given category, or None."""
    return _prompt_registry.get(category)


def get(name: str) -> Optional[Dict[str, Any]]:
    return _registry.get(name)


def list_tools() -> list:
    return list(_registry.keys())

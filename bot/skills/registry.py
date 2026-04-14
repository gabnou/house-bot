from pathlib import Path
from typing import Callable, Any, Dict, Optional

_registry: Dict[str, Dict[str, Any]] = {}
_prompt_registry: Dict[str, Callable[[], str]] = {}

# Override files live here: bot/prompts/{category}.txt
_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


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
    """Return a callable that yields the prompt text for the given category.

    If an override file (bot/prompts/{category}.txt) exists it takes precedence
    over the Python default, enabling hot-reload without a server restart.
    """
    override_file = _PROMPTS_DIR / f"{category}.txt"
    if override_file.exists():
        def _override() -> str:
            return override_file.read_text(encoding="utf-8")
        return _override
    return _prompt_registry.get(category)


def get_prompt_text(category: str) -> Optional[str]:
    """Return the current prompt string (override or default) for the given category."""
    fn = get_prompt(category)
    return fn() if fn else None


def list_prompt_categories() -> list[str]:
    """Return all registered prompt categories."""
    return list(_prompt_registry.keys())


def get(name: str) -> Optional[Dict[str, Any]]:
    return _registry.get(name)


def list_tools() -> list:
    return list(_registry.keys())

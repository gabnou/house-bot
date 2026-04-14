from typing import Any, Dict


def format_tool_reply(result: Any) -> str:
    """Turn a tool result into a user-facing text reply."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        if result.get("message"):
            return result["message"]
        if result.get("reply"):
            return result["reply"]
        try:
            import json

            return json.dumps(result, ensure_ascii=False)
        except Exception:
            return str(result)
    return str(result)

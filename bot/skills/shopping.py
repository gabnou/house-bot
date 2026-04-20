import re
from typing import List, Optional, Any, Dict
from pydantic import BaseModel

from services.shopping_db import (
    add_item,
    add_and_mark_bought,
    remove_item,
    show_list,
    clear_list,
    recent_bought,
    get_pending_items,
    mark_bought,
)
from .registry import register, register_prompt
from .schemas import ToolOutput


class ItemModel(BaseModel):
    name: str
    category: Optional[str] = "other"


class AddItemsIn(BaseModel):
    items: Optional[List[ItemModel]] = None
    name: Optional[str] = None
    category: Optional[str] = "other"


class RemoveItemsIn(BaseModel):
    names: Optional[List[str]] = None
    name: Optional[str] = None


class BoughtItemsIn(BaseModel):
    items: Optional[List[ItemModel]] = None
    name: Optional[str] = None
    category: Optional[str] = "other"


class ShowIn(BaseModel):
    category: Optional[str] = None


_STOP_WORDS = {"for", "the", "a", "an", "of", "to", "and", "or", "with", "in", "on", "some"}


def _word_overlap_score(query: str, candidate: str) -> float:
    """Word-token overlap between two strings.
    Handles translation variants (e.g. 'detergent for dishwashers' vs 'dishwasher detergent').
    Partial prefix matching (min 4 chars) covers plurals and inflections.
    Returns a score 0.0–1.0 (fraction of meaningful words that match)."""
    def tokens(s: str) -> set:
        return set(re.findall(r'\w+', s.lower())) - _STOP_WORDS

    wa = tokens(query)
    wb = tokens(candidate)
    if not wa or not wb:
        return 0.0
    matches = sum(
        1 for w in wa
        if any(
            w == v or (
                len(w) >= 4 and len(v) >= 4
                and (w.startswith(v[:4]) or v.startswith(w[:4]))
            )
            for v in wb
        )
    )
    return matches / max(len(wa), len(wb))


def _format_result_with_list(messages: List[str]) -> Dict[str, Any]:
    result = "\n".join(messages)
    updated = show_list()
    recent = recent_bought()
    reply = f"{result}\n\n{updated}\n\n{recent}" if recent else f"{result}\n\n{updated}"
    return {"ok": True, "message": reply}


def add_items_tool(payload: dict) -> Dict[str, Any]:
    req = AddItemsIn(**(payload or {}))
    items: List[ItemModel] = []
    if req.items:
        items = req.items
    elif req.name:
        items = [ItemModel(name=req.name, category=(req.category or "other"))]
    else:
        return {"ok": False, "message": "No items provided."}

    messages = []
    for it in items:
        messages.append(add_item(it.name, it.category or "other"))

    return _format_result_with_list(messages)


def remove_items_tool(payload: dict) -> Dict[str, Any]:
    req = RemoveItemsIn(**(payload or {}))
    names: List[str] = []
    if req.names:
        names = req.names
    elif req.name:
        names = [req.name]
    else:
        return {"ok": False, "message": "No item names provided to remove."}

    pending = get_pending_items()
    messages = []
    for n in names:
        res = remove_item(n)
        if not res.startswith("⚠️"):
            messages.append(res)
            continue
        # Fuzzy fallback 1: bidirectional substring
        # e.g. "milk" matches "whole milk" AND "whole milk" matches "milk"
        matched = [p for p in pending if n.lower() in p.lower() or p.lower() in n.lower()]
        if matched:
            messages.append(remove_item(matched[0]))
            continue
        # Fuzzy fallback 2: word-token overlap (handles translated forms)
        # e.g. "detergent for dishwashers" → "dishwasher detergent"
        matched_overlap = [p for p in pending if _word_overlap_score(n, p) >= 0.5]
        if matched_overlap:
            messages.append(remove_item(matched_overlap[0]))
            continue
        messages.append(res)

    return _format_result_with_list(messages)


def bought_items_tool(payload: dict) -> Dict[str, Any]:
    req = BoughtItemsIn(**(payload or {}))
    items: List[ItemModel] = []
    if req.items:
        items = req.items
    elif req.name:
        items = [ItemModel(name=req.name, category=(req.category or "other"))]
    else:
        return {"ok": False, "message": "No items provided."}

    pending = get_pending_items()
    messages: List[str] = []

    for it in items:
        # Try direct mark_bought first
        res = mark_bought(it.name)
        if res.startswith("✅"):
            messages.append(res)
            continue
        # Fuzzy fallback 1: bidirectional substring
        matched = [p for p in pending if it.name.lower() in p.lower() or p.lower() in it.name.lower()]
        if matched:
            messages.append(mark_bought(matched[0]))
            continue
        # Fuzzy fallback 2: word-token overlap (handles translated forms)
        matched_overlap = [p for p in pending if _word_overlap_score(it.name, p) >= 0.5]
        if matched_overlap:
            messages.append(mark_bought(matched_overlap[0]))
            continue
        # Otherwise add and mark as bought
        messages.append(add_and_mark_bought(it.name, it.category or "other"))

    return _format_result_with_list(messages)


def show_tool(payload: dict) -> Dict[str, Any]:
    req = ShowIn(**(payload or {}))
    updated = show_list(req.category)
    recent = recent_bought()
    if recent:
        return {"ok": True, "message": f"{updated}\n\n{recent}"}
    return {"ok": True, "message": updated}


def clear_tool(payload: dict) -> Dict[str, Any]:
    msg = clear_list()
    return {"ok": True, "message": msg}


# Register tools
register(
    "shopping.add",
    add_items_tool,
    input_schema=AddItemsIn,
    output_schema=ToolOutput,
    desc="Add one or more items to the shopping list",
)

register(
    "shopping.remove",
    remove_items_tool,
    input_schema=RemoveItemsIn,
    output_schema=ToolOutput,
    desc="Remove items from the shopping list",
)

register(
    "shopping.bought",
    bought_items_tool,
    input_schema=BoughtItemsIn,
    output_schema=ToolOutput,
    desc="Mark items as bought (or add-and-mark if not present)",
)

register(
    "shopping.show",
    show_tool,
    input_schema=ShowIn,
    output_schema=ToolOutput,
    desc="Show pending shopping list (optional category)",
)

register(
    "shopping.clear",
    clear_tool,
    input_schema=None,
    output_schema=ToolOutput,
    desc="Clear the pending shopping list (mark as bought)",
)


def prompt() -> str:
    return """You are a shopping list assistant named \"house-bot\". Interpret the message and respond ONLY with a valid JSON object.

Available actions:
- add: adds items. {\"action\": \"add\", \"items\": [{\"name\": \"...\", \"category\": \"...\"}]}
- remove: removes items from the list. {\"action\": \"remove\", \"names\": [\"...\"]}
- bought: marks items as bought. {\"action\": \"bought\", \"items\": [{\"name\": \"...\", \"category\": \"...\"}]}
- show: shows the list. {\"action\": \"show\", \"category\": null|\"food\"|\"other\"|\"clothing\"|\"health\"}
- clear: clears the entire list. {\"action\": \"clear\"}

Valid categories: food, other, clothing, health.
Medicine, drugs, vitamins → health. Clothes, shoes, accessories → clothing.

Examples:
Message: \"shopping add milk and eggs\"
Response: {\"action\": \"add\", \"items\": [{\"name\": \"milk\", \"category\": \"food\"}, {\"name\": \"eggs\", \"category\": \"food\"}]}

Message: \"shopping add aspirin and vitamin C\"
Response: {\"action\": \"add\", \"items\": [{\"name\": \"aspirin\", \"category\": \"health\"}, {\"name\": \"vitamin C\", \"category\": \"health\"}]}

Message: \"shopping add new shoes\"
Response: {\"action\": \"add\", \"items\": [{\"name\": \"new shoes\", \"category\": \"clothing\"}]}

Message: \"shopping show\"
Response: {\"action\": \"show\", \"category\": null}

Message: \"shopping list\"
Response: {\"action\": \"show\", \"category\": null}

Message: \"shopping what's on the list?\"
Response: {\"action\": \"show\", \"category\": null}

Message: \"shopping what's missing for food?\"
Response: {\"action\": \"show\", \"category\": \"food\"}

Message: \"shopping remove the bread\"
Response: {\"action\": \"remove\", \"names\": [\"bread\"]}

Message: \"shopping remove eggs and butter\"
Response: {\"action\": \"remove\", \"names\": [\"eggs\", \"butter\"]}

Message: \"shopping I bought milk and bread\"
Response: {\"action\": \"bought\", \"items\": [{\"name\": \"milk\", \"category\": \"food\"}, {\"name\": \"bread\", \"category\": \"food\"}]}

Message: \"shopping bought milk and bread\"
Response: {\"action\": \"bought\", \"items\": [{\"name\": \"milk\", \"category\": \"food\"}, {\"name\": \"bread\", \"category\": \"food\"}]}

Message: \"shopping clear\"
Response: {\"action\": \"clear\"}

Respond ONLY with JSON, no additional text, no markdown, no explanations."""


register_prompt("shopping", prompt)

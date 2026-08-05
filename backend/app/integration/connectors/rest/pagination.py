"""Phase 2.2.1 SRS ACT-INT-FR-105 — bounded pagination.

Three declared styles: ``offset_limit`` (``offset``/``limit`` query
parameters, stop once a page returns fewer than ``page_size`` items),
``page_number`` (a 1-based ``page`` counter, same stop rule), and
``cursor`` (an opaque token echoed back by the server; stop once it stops
supplying one). All three share one hard rule (``ACT-INT-FR-105``'s
"never an unbounded fetch"): the number of pages fetched is capped at
``min(declared max_pages, _HARD_MAX_PAGES)`` regardless of what the
declaration or the remote server claims — a misconfigured or
misbehaving API that always returns "more" cannot make this driver loop
forever or accumulate unbounded memory (AC-14).

``fetch_page`` is supplied by the caller (``invoker.py``) as a plain
callable — this module performs no HTTP of its own, which is what keeps
it trivially unit-testable against canned, in-memory page fixtures with
no server at all."""

from __future__ import annotations

from typing import Any, Callable, Mapping

_HARD_MAX_PAGES = 100
_DEFAULT_MAX_PAGES = 20
_DEFAULT_PAGE_SIZE = 50


class PaginationError(Exception):
    """An unsupported or malformed pagination declaration reached this
    driver — should never happen for a declaration ``parse_declaration``
    already validated; kept as a defensive, explicit failure rather than a
    silent no-op."""


def _items_at(page: Any, items_field: str | None) -> list[Any]:
    if not items_field:
        return list(page) if isinstance(page, list) else []
    node: Any = page
    for part in items_field.split("."):
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return []
    return list(node) if isinstance(node, list) else []


def run_pagination(spec: Mapping[str, Any], fetch_page: Callable[[Mapping[str, Any]], Any]) -> list[Any]:
    style = spec.get("style")
    page_size = int(spec.get("page_size", _DEFAULT_PAGE_SIZE))
    max_pages = min(int(spec.get("max_pages", _DEFAULT_MAX_PAGES)), _HARD_MAX_PAGES)
    items_field = spec.get("items_field")
    results: list[Any] = []

    if style == "offset_limit":
        offset = int(spec.get("start_offset", 0))
        for _ in range(max_pages):
            page = fetch_page({"offset": offset, "limit": page_size})
            items = _items_at(page, items_field)
            results.extend(items)
            if len(items) < page_size:
                break
            offset += page_size
    elif style == "page_number":
        page_number = int(spec.get("start_page", 1))
        for _ in range(max_pages):
            page = fetch_page({"page": page_number, "page_size": page_size})
            items = _items_at(page, items_field)
            results.extend(items)
            if len(items) < page_size:
                break
            page_number += 1
    elif style == "cursor":
        cursor_field = spec.get("cursor_field", "next_cursor")
        cursor: str | None = None
        for _ in range(max_pages):
            page = fetch_page({"cursor": cursor} if cursor else {})
            items = _items_at(page, items_field)
            results.extend(items)
            cursor = page.get(cursor_field) if isinstance(page, dict) else None
            if not cursor:
                break
    else:
        raise PaginationError(f"unsupported pagination style {style!r}")

    return results

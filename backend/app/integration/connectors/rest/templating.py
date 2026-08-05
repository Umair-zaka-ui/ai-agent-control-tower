"""Phase 2.2.1 SRS ACT-INT-FR-104 — injection-safe request templating.

Tool arguments are always *data*, never allowed to alter a request's
structure — the same principle ``app.runtime.tools.http_executor``'s own
``_build_target_url`` already enforces for the Milestone 1 HTTP tool
action (a scheme/host smuggled into a path argument is discarded, never
resolved as a new target), applied here at the argument-rendering layer
instead: every value substituted into a path template is percent-encoded
with no "safe" characters at all (``quote(value, safe="")``), so a value
like ``"123/../admin"`` becomes a single, inert path segment
(``"123%2F..%2Fadmin"``) that can never introduce an extra ``/`` and
escape the declared endpoint (AC-06). Header and query values are
rejected outright if they contain a control character (``\\r``/``\\n``/
NUL) that could otherwise smuggle a second header or split the request
line (AC-07).

``TemplateRenderError`` is a small, local exception — this module has no
dependency on the platform's error taxonomy (``app.identity.errors``);
translating a rendering failure into the platform's
``RestTemplateInvalidError`` is the bridge's job (``invoker.py``), exactly
as ``GovernedHttpClient.request()`` itself never raises for an egress
denial and leaves interpretation to its caller."""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

_CONTROL_CHARS_RE = re.compile(r"[\r\n\x00]")


class TemplateRenderError(Exception):
    """A REST endpoint's request could not be safely rendered from the
    supplied arguments — see ``invoker.py`` for how this becomes
    ``RestTemplateInvalidError`` at the platform boundary."""


def render_path(path_template: str, path_params: tuple[str, ...], arguments: Mapping[str, Any]) -> str:
    """Substitutes every ``{name}`` token in ``path_template`` with the
    corresponding argument, percent-encoded with no safe characters at all
    — this is what makes a ``/`` or ``..`` inside an argument value inert
    (AC-06): it can only ever contribute to the *content* of the single
    path segment it was declared for, never split into additional ones."""
    rendered = path_template
    for name in path_params:
        if name not in arguments or arguments[name] is None:
            raise TemplateRenderError(f"missing required path argument '{name}'")
        rendered = rendered.replace("{" + name + "}", quote(str(arguments[name]), safe=""))
    return rendered


def render_query(query_params: Mapping[str, str], arguments: Mapping[str, Any]) -> dict[str, str]:
    """``query_params`` maps a query-string key to the argument name that
    supplies its value; an argument the caller didn't supply is simply
    omitted from the query string (optional, not an error)."""
    result: dict[str, str] = {}
    for query_key, arg_name in query_params.items():
        value = arguments.get(arg_name)
        if value is None:
            continue
        text = str(value)
        if _CONTROL_CHARS_RE.search(text):
            raise TemplateRenderError(f"query argument '{arg_name}' contains invalid characters")
        result[query_key] = text
    return result


def render_headers(header_params: Mapping[str, str], arguments: Mapping[str, Any]) -> dict[str, str]:
    """``header_params`` maps a header name to the argument name that
    supplies its value. A value containing ``\\r``/``\\n``/NUL is rejected
    outright (AC-07) rather than passed through and left to whatever the
    underlying HTTP client does with it — this module never lets such a
    value reach a real request in the first place."""
    result: dict[str, str] = {}
    for header_name, arg_name in header_params.items():
        value = arguments.get(arg_name)
        if value is None:
            continue
        text = str(value)
        if _CONTROL_CHARS_RE.search(text):
            raise TemplateRenderError(f"header argument '{arg_name}' contains invalid characters")
        result[header_name] = text
    return result


def render_body(body_fields: tuple[str, ...], arguments: Mapping[str, Any]) -> dict[str, Any] | None:
    """``body_fields`` names arguments placed into the JSON request body,
    each as its own key with its own value — never string-interpolated
    into a body template, so an argument value (whatever it is: a string,
    a number, a nested object) is always JSON-serialized as *data*, never
    capable of altering the body's own structure."""
    if not body_fields:
        return None
    return {name: arguments[name] for name in body_fields if name in arguments and arguments[name] is not None}


def build_request_url(base_url: str, rendered_path: str, query: Mapping[str, str]) -> str:
    """Joins the connector instance's own declared, trusted ``base_url``
    with an already-rendered (argument-safe) path and query — the base's
    scheme/host are never influenced by anything here; only its own path
    prefix (if any) and the rendered suffix are combined."""
    base = urlsplit(base_url)
    base_path = base.path.rstrip("/") if base.path not in ("", "/") else ""
    safe_suffix = rendered_path if rendered_path.startswith("/") else "/" + rendered_path
    combined_path = (base_path + safe_suffix) or "/"
    query_string = urlencode(query) if query else ""
    return urlunsplit((base.scheme, base.netloc, combined_path, query_string, ""))

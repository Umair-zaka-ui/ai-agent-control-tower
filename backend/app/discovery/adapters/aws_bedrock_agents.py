"""V7.5 - the ONE cloud discovery adapter: **Agents for Amazon Bedrock**
(``AWS_BEDROCK_AGENTS``). ADR-0024.

This module is the single deliberate product-change exception of the
post-Milestone-5 validation programme. It exists so that V8 can red-team
cloud discovery; it was built through the architecture gate (reuse-first,
containment-preserved, regression-clean), not the red-team gate, and it is
drawn as narrowly as possible:

* **Discovery plane only.** It produces ``NormalizedObservation``s for the
  Phase 5.2 pipeline (append-only evidence -> deterministic reconciliation ->
  an agent at ``origin_category=EXTERNAL`` / ``control_state=DISCOVERED``).
  It emits no detection, threat, posture, graph or gateway signal and imports
  nothing from those packages (``tests/discovery/test_aws_bedrock_agents_
  adapter.py`` asserts the import set structurally). F6-1 (gateway-enforced
  agents are invisible to detection) is **not** addressed here - cloud-
  discovered agents inherit it by design, for V8 to observe.
* **One provider, one operation.** ``ListAgents`` on the Agents for Amazon
  Bedrock build-time API (``POST /agents/``, endpoint
  ``bedrock-agent.<region>.amazonaws.com``, SigV4 signing name ``bedrock`` per
  botocore's ``bedrock-agent/2023-06-05`` service model). No ``GetAgent``, no
  aliases, no versions, no knowledge bases, flows, prompts, guardrails,
  foundation models, Lambda, ECS, EC2 or SageMaker inventory - see
  :func:`is_bedrock_agent` for the conservative agent-definition filter.
* **Read-only by construction and by scope.** The only network call this
  module can make is the one ``client.request`` in :meth:`_list_agents`
  (asserted structurally); the credential it needs is a scoped read-only IAM
  principal whose policy allows exactly ``REQUIRED_IAM_ACTIONS``. AWS's
  ``ListAgents`` is a POST-bodied *list* operation (``maxResults`` /
  ``nextToken`` in the body); read-only-ness comes from the operation and the
  IAM scope, not from the HTTP verb.
* **Authenticate the SOURCE, never extend internal identity** (V7 SR point
  3). The AWS credential authenticates ACT-to-AWS. It never becomes an ACT
  principal, never touches ``users``/grants, and a discovered Bedrock agent
  gets no internal authority - ``GOVERNED`` stays unreachable for it (ADR-0023).
* **No new primitive.** ``GovernedHttpClient`` (``app.integration.sdk``) is
  the sole network path - egress allowlist, SSRF/rebinding pinning, redirect
  re-validation and the 1 MiB response cap are inherited, not re-implemented.
  The allowed host is *derived* from a pattern-validated ``region`` (or an
  explicitly bounded ``endpoint_url``), never a free-form host list.
* **Request signing is the one NEW capability**, justified in ADR-0024: the
  5.2 reference adapter authenticates with a bearer header; AWS requires
  Signature Version 4. ``boto3``/``botocore`` would be a second network
  primitive outside ``GovernedHttpClient``, so SigV4 is implemented here in
  ~40 lines of standard library (``hmac``/``hashlib``) - a *header
  computation*, not a transport. It signs exactly the bytes and path the
  governed executor puts on the wire (``_encode_json_as_sent`` mirrors httpx's
  JSON encoding; ``_path_as_sent`` mirrors ``http_executor._build_target_url``,
  which drops a trailing slash - Smithy URI matching treats trailing slashes
  as optional, so ``/agents`` routes to ``ListAgents``). The test file pins
  both mirrors against the real ``httpx``/executor behaviour.
* **No AWS error body is ever recorded.** A SigV4 rejection message from AWS
  echoes the canonical request, which can include a session token. Run
  errors therefore carry the HTTP status and a fixed classification only -
  never response bytes.

Everything else - no DB session anywhere in ``fetch``'s signature (AC-06),
scrubbing before persistence, bounded pages/items, fail-open partial fetch,
tenant scoping via the owning ``DiscoverySource`` - is the 5.2 framework,
reused unchanged.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import urlsplit

from app.discovery.adapters.base import (
    DiscoveryAdapter,
    DiscoveryAdapterDescriptor,
    DiscoveryFetchResult,
    NormalizedObservation,
    RawDiscoveryItem,
)
from app.discovery.adapters.registry import register
from app.identity.errors import ErrorCode, IdentityError
from app.integration.base import validate_configuration_schema
from app.integration.sdk import GovernedHttpClient

ADAPTER_KEY = "AWS_BEDROCK_AGENTS"

# --- the provider facts this adapter is built on (all public AWS reference) ---
SERVICE_ENDPOINT_PREFIX = "bedrock-agent"      # bedrock-agent.<region>.amazonaws.com
SIGNING_NAME = "bedrock"                       # botocore bedrock-agent/2023-06-05 metadata.signingName
LIST_AGENTS_METHOD = "POST"                    # ListAgents: POST /agents/ (rest-json)
LIST_AGENTS_PATH = "/agents/"
#: The complete IAM scope the source credential needs. One list action; no
#: Get*/Create*/Update*/Delete*/Prepare*/Invoke*. ``ListAgents`` supports no
#: resource-level restriction, so the policy's Resource is ``"*"``.
REQUIRED_IAM_ACTIONS: tuple[str, ...] = ("bedrock:ListAgents",)

#: AgentSummary.agentStatus values (AWS API reference). ``DELETING`` is the
#: one status the filter excludes: AWS reports the construct as on its way
#: out, and discovering it would create an agent only to stale it next sweep.
KNOWN_AGENT_STATUSES: tuple[str, ...] = (
    "CREATING", "PREPARING", "PREPARED", "NOT_PREPARED", "DELETING", "FAILED", "VERSIONING", "UPDATING",
)
EXCLUDED_AGENT_STATUSES: frozenset[str] = frozenset({"DELETING"})

_AGENT_ID_RE = re.compile(r"^[0-9a-zA-Z]{10}$")            # AgentSummary.agentId pattern
_ACCESS_KEY_ID_RE = re.compile(r"^[A-Z0-9]{16,128}$")       # AKIA.../ASIA... shapes
REGION_PATTERN = r"^[a-z]{2}(-gov)?-[a-z]+-[0-9]$"          # us-east-1, eu-west-3, us-gov-west-1, ...
# Origin only - scheme://host[:port] - so a path prefix can never be smuggled
# in front of the operation path.
ENDPOINT_URL_PATTERN = r"^https?://[A-Za-z0-9.\-]+(:[0-9]{1,5})?/?$"

_DEFAULT_PAGE_SIZE = 100
_MAX_PAGE_SIZE = 200          # AWS allows up to 1000; kept at the reference adapter's ceiling
_DEFAULT_MAX_PAGES = 20
_MAX_PAGES = 100
_MAX_ITEMS_PER_FETCH = _MAX_PAGE_SIZE * _MAX_PAGES   # the absolute DoS bound, as in the reference adapter
_TIMEOUT_SECONDS = 15.0
#: httpx sets exactly this Content-Type for ``json=``; AWS asks that a present
#: Content-Type be signed, so it is signed with the value actually transmitted
#: (pinned against ``httpx.Request`` in the test file).
_CONTENT_TYPE_AS_SENT = "application/json"

_CONFIG_SCHEMA: dict = {
    "type": "object",
    "required": ["region"],
    "properties": {
        "region": {"type": "string", "pattern": REGION_PATTERN},
        # Optional override for a FIPS/VPC endpoint (must be https *.amazonaws.com)
        # or, for the lab/test path only, a host listed in ``local_dev_hosts``.
        "endpoint_url": {"type": "string", "pattern": ENDPOINT_URL_PATTERN},
        "local_dev_hosts": {"type": "array", "items": {"type": "string"}},
        "allow_plaintext_http": {"type": "boolean"},
        "page_size": {"type": "integer", "minimum": 1, "maximum": _MAX_PAGE_SIZE, "default": _DEFAULT_PAGE_SIZE},
        "max_pages": {"type": "integer", "minimum": 1, "maximum": _MAX_PAGES, "default": _DEFAULT_MAX_PAGES},
    },
    # Tighter than the reference adapter: no unknown keys, so nothing like an
    # ``allowed_hosts`` list can be smuggled in - the host is always derived.
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# The agent-definition filter (pure, importable, asserted by tests)
# --------------------------------------------------------------------------- #
def is_bedrock_agent(summary: Any) -> bool:
    """The conservative answer to "what counts as an AI agent in AWS": exactly
    an *Agents for Amazon Bedrock* agent construct as ``ListAgents`` reports
    it - a mapping with the API's required ``agentId`` (10 alphanumerics) and
    ``agentName``, whose ``agentStatus`` is not ``DELETING``.

    Everything else in an AWS account is **not** an agent to this adapter:
    foundation models, knowledge bases, flows, prompts, guardrails, agent
    aliases and versions (deployment pointers, not agents), Lambda functions,
    ECS tasks, EC2 instances, SageMaker endpoints. None of those is ever
    listed - the adapter calls only ``ListAgents`` - and a malformed or
    foreign-shaped element inside ``agentSummaries`` is dropped here rather
    than observed, so a poisoned page cannot inflate the inventory."""
    if not isinstance(summary, Mapping):
        return False
    agent_id = summary.get("agentId")
    name = summary.get("agentName")
    if not isinstance(agent_id, str) or not _AGENT_ID_RE.match(agent_id):
        return False
    if not isinstance(name, str) or not name:
        return False
    status = summary.get("agentStatus")
    if isinstance(status, str) and status in EXCLUDED_AGENT_STATUSES:
        return False
    return True


def external_identifier(region: str, agent_id: str) -> str:
    """Deterministic, collision-resistant identity for reconciliation:
    ``bedrock-agent:<region>:<agentId>``. ``agentId`` is unique per account
    and region; the region prefix keeps two regional sources in one tenant
    from ever matching on the same ten characters. Deliberately not shaped
    like an ARN (``ListAgents`` does not return the account id, and a
    fabricated ARN would look authoritative without being one)."""
    return f"{SERVICE_ENDPOINT_PREFIX}:{region}:{agent_id}"


# --------------------------------------------------------------------------- #
# Credential (decrypted by the 5.2 service, parsed here, never persisted/logged)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _AwsCredential:
    access_key_id: str
    secret_access_key: str
    session_token: str | None


def _parse_credential(secret: str | None) -> _AwsCredential:
    """The source ``secret`` (encrypted at rest by ``credential_crypto``) is
    ``ACCESS_KEY_ID:SECRET_ACCESS_KEY`` or, for temporary STS credentials,
    ``ACCESS_KEY_ID:SECRET_ACCESS_KEY:SESSION_TOKEN``. All three parts live in
    the one encrypted field so that the plaintext ``config`` (returned by the
    source API) carries no credential material at all. Error messages here
    never include any part of the value."""
    if not secret:
        raise IdentityError(
            ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG,
            f"{ADAPTER_KEY} requires a read-only AWS credential as the source secret "
            "('ACCESS_KEY_ID:SECRET_ACCESS_KEY[:SESSION_TOKEN]'); none is configured.",
        )
    parts = secret.split(":", 2)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise IdentityError(
            ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG,
            f"{ADAPTER_KEY} credential is malformed: expected "
            "'ACCESS_KEY_ID:SECRET_ACCESS_KEY[:SESSION_TOKEN]'.",
        )
    if not _ACCESS_KEY_ID_RE.match(parts[0]):
        raise IdentityError(
            ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG,
            f"{ADAPTER_KEY} credential is malformed: the access key id has an unexpected shape.",
        )
    token = parts[2] if len(parts) == 3 and parts[2] else None
    return _AwsCredential(access_key_id=parts[0], secret_access_key=parts[1], session_token=token)


# --------------------------------------------------------------------------- #
# Signature Version 4 - a header computation over exactly what goes on the wire
# --------------------------------------------------------------------------- #
def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _encode_json_as_sent(payload: Mapping[str, Any]) -> bytes:
    """Byte-identical to what ``GovernedHttpClient`` -> ``execute_http_tool``
    -> ``httpx.Client.stream(..., json=payload)`` transmits (httpx
    ``encode_json``: compact separators, ``ensure_ascii=False``,
    ``allow_nan=False``). SigV4 hashes the payload, so this must match the
    wire bytes exactly; the test file pins it against ``httpx.Request``."""
    return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _path_as_sent(url: str) -> str:
    """The canonical URI must be the path the governed executor actually
    sends. ``app.runtime.tools.http_executor._build_target_url`` emits the
    URL's path with any trailing slash removed (root stays ``/``); mirrored
    here rather than imported, because this adapter deliberately depends on
    nothing below ``app.integration.sdk``. The test file pins the mirror."""
    path = urlsplit(url).path
    if path in ("", "/"):
        return "/"
    return path.rstrip("/")


def _signing_key(secret_access_key: str, date_stamp: str, region: str, service: str) -> bytes:
    k_date = _hmac_sha256(("AWS4" + secret_access_key).encode("utf-8"), date_stamp)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "aws4_request")


def _sigv4_authorization(*, method: str, canonical_uri: str, canonical_query: str,
                         headers: Mapping[str, str], payload: bytes, access_key_id: str,
                         secret_access_key: str, region: str, service: str, amz_date: str) -> str:
    """The AWS Signature Version 4 ``Authorization`` value for one request.
    ``headers`` are the headers to sign (lower-cased names, exact values as
    transmitted) - ``content-type``, ``host`` and ``x-amz-date`` here, plus
    ``x-amz-security-token`` for temporary credentials."""
    names = sorted(k.lower() for k in headers)
    lowered = {k.lower(): v for k, v in headers.items()}
    canonical_headers = "".join(f"{name}:{lowered[name].strip()}\n" for name in names)
    signed_headers = ";".join(names)
    canonical_request = "\n".join([
        method, canonical_uri, canonical_query, canonical_headers, signed_headers, _sha256_hex(payload),
    ])
    date_stamp = amz_date[:8]
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope, _sha256_hex(canonical_request.encode("utf-8")),
    ])
    signature = hmac.new(_signing_key(secret_access_key, date_stamp, region, service),
                         string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}")


def _signed_headers_for(method: str, url: str, payload: bytes, credential: _AwsCredential,
                        region: str, now: datetime) -> dict[str, str]:
    amz_date = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # ``host`` is what httpx sends: the URL's netloc verbatim (port included
    # only when the URL carries one explicitly - it never does for AWS).
    to_sign = {"content-type": _CONTENT_TYPE_AS_SENT, "host": urlsplit(url).netloc, "x-amz-date": amz_date}
    if credential.session_token:
        to_sign["x-amz-security-token"] = credential.session_token
    authorization = _sigv4_authorization(
        method=method, canonical_uri=_path_as_sent(url), canonical_query="", headers=to_sign,
        payload=payload, access_key_id=credential.access_key_id,
        secret_access_key=credential.secret_access_key, region=region, service=SIGNING_NAME,
        amz_date=amz_date,
    )
    out = {"Authorization": authorization, "X-Amz-Date": amz_date}
    if credential.session_token:
        out["X-Amz-Security-Token"] = credential.session_token
    return out


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Endpoint derivation - the allowed host is computed, never declared
# --------------------------------------------------------------------------- #
def _effective_endpoint(configuration: Mapping[str, Any]) -> str:
    override = configuration.get("endpoint_url")
    if override:
        return str(override).rstrip("/")
    return f"https://{SERVICE_ENDPOINT_PREFIX}.{configuration['region']}.amazonaws.com"


def _classify_status(status: int | None) -> str:
    if status is None:
        return "no HTTP response (transport error, timeout, or egress denial)"
    if status == 400:
        return "request rejected by AWS (ValidationException)"
    if status == 403:
        return ("access denied or signature rejected (AccessDeniedException / signature mismatch) - "
                f"check the read-only credential and its {', '.join(REQUIRED_IAM_ACTIONS)} permission")
    if status == 429:
        return "throttled (ThrottlingException)"
    if status >= 500:
        return "AWS service error"
    return "unexpected status"


def _failure_message(result: Any, *, page: int) -> str:
    """Status + fixed classification only. The AWS response body is
    deliberately never recorded (see the module docstring)."""
    return (f"{ADAPTER_KEY} ListAgents page {page}: status={result.status} error={result.error} "
            f"egress={result.egress_decision.reason} - {_classify_status(result.status)}. "
            "Response body not recorded.")


# --------------------------------------------------------------------------- #
# The adapter
# --------------------------------------------------------------------------- #
@register(ADAPTER_KEY)
class AwsBedrockAgentsAdapter(DiscoveryAdapter):
    def describe(self) -> DiscoveryAdapterDescriptor:
        return DiscoveryAdapterDescriptor(
            adapter_key=ADAPTER_KEY,
            display_name="AWS - Agents for Amazon Bedrock (read-only inventory)",
            config_schema=_CONFIG_SCHEMA,
            requires_secret=True,
        )

    def validate_configuration(self, configuration: Mapping[str, Any]) -> None:
        try:
            validate_configuration_schema(configuration, _CONFIG_SCHEMA)
        except Exception as exc:  # noqa: BLE001 - re-raise as this domain's own error code
            raise IdentityError(ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG, str(exc)) from exc

        local_dev_hosts = {str(h).lower() for h in configuration.get("local_dev_hosts", ())}
        override = configuration.get("endpoint_url")
        if override:
            parts = urlsplit(str(override))
            host = (parts.hostname or "").lower()
            if host not in local_dev_hosts and not (parts.scheme == "https" and host.endswith(".amazonaws.com")):
                raise IdentityError(
                    ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG,
                    "endpoint_url must be an https *.amazonaws.com endpoint (FIPS/VPC) or a host "
                    "listed in local_dev_hosts.",
                )
        if configuration.get("allow_plaintext_http") and not local_dev_hosts:
            raise IdentityError(
                ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG,
                "allow_plaintext_http is only permitted together with local_dev_hosts.",
            )

    def build_client(self, configuration: Mapping[str, Any]) -> GovernedHttpClient:
        host = urlsplit(_effective_endpoint(configuration)).hostname or ""
        return GovernedHttpClient(
            allowed_hosts=frozenset({host}),   # exactly one host, derived - never a declared list
            allow_plaintext_http=bool(configuration.get("allow_plaintext_http", False)),
            local_dev_hosts=frozenset(configuration.get("local_dev_hosts", ())),
        )

    def _list_agents(self, client: GovernedHttpClient, url: str, payload: dict,
                     credential: _AwsCredential, region: str):
        """THE single network call site in this module (asserted
        structurally). One operation - ``ListAgents`` - signed over exactly
        the bytes and path the governed client transmits."""
        body = _encode_json_as_sent(payload)
        headers = _signed_headers_for(LIST_AGENTS_METHOD, url, body, credential, region, _utcnow())
        return client.request(LIST_AGENTS_METHOD, url, headers=headers, json_body=payload,
                              timeout_seconds=_TIMEOUT_SECONDS)

    def fetch(
        self,
        client: GovernedHttpClient,
        configuration: Mapping[str, Any],
        secret: str | None,
        checkpoint: Mapping[str, Any] | None,
    ) -> DiscoveryFetchResult:
        credential = _parse_credential(secret)
        region = str(configuration["region"])
        url = _effective_endpoint(configuration) + LIST_AGENTS_PATH
        page_size = min(int(configuration.get("page_size", _DEFAULT_PAGE_SIZE)), _MAX_PAGE_SIZE)
        max_pages = min(int(configuration.get("max_pages", _DEFAULT_MAX_PAGES)), _MAX_PAGES)

        next_token: str | None = (checkpoint or {}).get("next_token") or None
        resuming = next_token is not None
        items: list[RawDiscoveryItem] = []
        degraded = False
        degraded_reason: str | None = None
        pages_fetched = 0

        while pages_fetched < max_pages:
            payload: dict = {"maxResults": page_size}
            if next_token:
                payload["nextToken"] = next_token
            result = self._list_agents(client, url, payload, credential, region)
            pages_fetched += 1

            if not result.success or result.status != 200:
                if pages_fetched == 1:
                    if resuming and result.status == 400:
                        # AWS pagination tokens are opaque and expire. A
                        # resumption token AWS no longer accepts must not
                        # leave the source stuck on a perpetual FAILED run:
                        # fall back to ONE fresh sweep from the beginning.
                        resuming = False
                        next_token = None
                        pages_fetched = 0
                        continue
                    # Hard failure on the first page: unreachable, rejected,
                    # or throttled outright - a FAILED run, never a platform
                    # error, and never a deletion or a staleness finding.
                    raise IdentityError(ErrorCode.DISCOVERY_SOURCE_UNREACHABLE, _failure_message(result, page=1))
                # A later page failed (throttle, hiccup): keep the evidence
                # already collected, degrade to PARTIAL, resume from this
                # page's token next sweep (SRS M5.2 §11 - fails open).
                degraded, degraded_reason = True, _failure_message(result, page=pages_fetched)
                break

            body = self._parse_body(result.response_body_redacted)
            summaries = body.get("agentSummaries")
            for summary in (summaries if isinstance(summaries, list) else []):
                if not is_bedrock_agent(summary):
                    continue
                items.append(RawDiscoveryItem(
                    external_identifier=external_identifier(region, summary["agentId"]),
                    payload={**dict(summary), "region": region},
                ))
                if len(items) >= _MAX_ITEMS_PER_FETCH:
                    token = body.get("nextToken")
                    return DiscoveryFetchResult(
                        items=tuple(items), next_checkpoint={"next_token": token} if token else {},
                        complete=not token, degraded=True, degraded_reason="absolute item bound reached")

            token = body.get("nextToken")
            next_token = token if isinstance(token, str) and token else None
            if next_token is None:
                return DiscoveryFetchResult(items=tuple(items), next_checkpoint={}, complete=True,
                                            degraded=degraded, degraded_reason=degraded_reason)

        return DiscoveryFetchResult(items=tuple(items), next_checkpoint={"next_token": next_token},
                                    complete=False, degraded=True,
                                    degraded_reason=degraded_reason or "max_pages reached")

    @staticmethod
    def _parse_body(raw: bytes | dict | None) -> dict:
        """Same contract as the reference adapter: ``response_body_redacted``
        is raw bytes; malformed JSON is an empty page, not an exception."""
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def normalize(self, item: RawDiscoveryItem) -> NormalizedObservation:
        raw = item.payload
        description = raw.get("description")
        return NormalizedObservation(
            external_identifier=item.external_identifier,
            name=str(raw.get("agentName") or item.external_identifier),
            agent_type="ASSISTANT",
            origin_provider=ADAPTER_KEY,
            description=description if isinstance(description, str) else None,
            # AWS is authoritative for its own agent inventory - confidence
            # 1.00, a deterministic source-class constant (never payload-derived).
            confidence=Decimal("1.00"),
            raw=dict(raw),
        )


__all__ = [
    "ADAPTER_KEY", "REQUIRED_IAM_ACTIONS", "SIGNING_NAME", "SERVICE_ENDPOINT_PREFIX",
    "LIST_AGENTS_METHOD", "LIST_AGENTS_PATH", "KNOWN_AGENT_STATUSES", "EXCLUDED_AGENT_STATUSES",
    "REGION_PATTERN", "AwsBedrockAgentsAdapter", "is_bedrock_agent", "external_identifier",
]

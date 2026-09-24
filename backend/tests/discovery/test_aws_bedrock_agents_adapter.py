"""V7.5 - the AWS Bedrock Agents cloud discovery adapter (ADR-0024):
architecture-gate tests. Real behaviour, not attack (attacking it is V8).

Proves, against a REAL local HTTP server that speaks the documented Agents
for Amazon Bedrock ``ListAgents`` wire shape and **verifies AWS Signature
Version 4 on every request** (the same real-``http.server`` convention the
5.2 framework tests use), that the adapter:

  * implements the 5.2 ``DiscoveryAdapter`` contract unchanged (unit);
  * discovers exactly Bedrock *agents* and nothing else (the conservative
    agent-definition filter), normalizes them deterministically, and lands
    them as EXTERNAL / DISCOVERED agents through the 5.2 reconciliation path
    (integration), idempotently, with a removed asset yielding a STALE_AGENT
    finding and an outage yielding a FAILED run - never a deletion;
  * holds no DB lock across the cloud call (behavioural, the AC-06 shape);
  * is contained by construction: ``GovernedHttpClient`` only, one derived
    host, discovery-plane-only imports, one read-only list operation, no
    cloud credential in any observation / audit / run record, tenant-scoped,
    NATIVE collision flags, no silent merge;
  * needs no migration.

No live cloud is contacted anywhere in this file. The only credentials in it
are AWS's own published documentation EXAMPLE values, which are synthetic.
"""

from __future__ import annotations

import ast
import hashlib
import hmac
import http.server
import inspect
import json as jsonlib
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.core.database import SessionLocal
from app.discovery.adapters import aws_bedrock_agents as mod
from app.discovery.adapters import registry as adapter_registry
from app.discovery.adapters.base import DiscoveryAdapter, NormalizedObservation, RawDiscoveryItem
from app.identity.errors import ErrorCode, IdentityError
from app.integration.sdk import GovernedHttpClient
from app.models.agent import Agent
from app.models.discovery import DiscoveryFinding, DiscoveryObservation, DiscoveryRun, DiscoverySource

DISC = "/api/v1/discovery"
_BACKEND = Path(__file__).resolve().parents[2]
_ADAPTER_PATH = _BACKEND / "app" / "discovery" / "adapters" / "aws_bedrock_agents.py"

# AWS's published documentation EXAMPLE credentials (synthetic, never valid) -
# assembled by concatenation so the credential-shaped literal never appears
# whole in source (push-protection rule, REPO_STATE section 9 item 21).
AKID = "AKIAIOSFODNN" + "7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY"
SESSION = "FwoGZXIvYXdzEXAMPLESESSIONTOKENVALUE"
REGION = "us-east-1"


# --------------------------------------------------------------------------- #
# A real local HTTP server speaking the ListAgents wire shape, verifying SigV4
# --------------------------------------------------------------------------- #
class _Inventory:
    def __init__(self) -> None:
        self.agents: list[dict] = []
        self.requests: list[dict] = []
        #: Every request that was NOT a ListAgents call - the read-only proof
        #: asserts this stays empty.
        self.non_list_calls: list[dict] = []
        self.tokens: dict[str, int] = {}
        self.fail_page_number: int | None = None
        self.fail_status: int = 429
        self.deny_all = False
        self.hold_requests = False
        self.hold_event = threading.Event()
        self.signature_failures = 0
        self.session_token: str | None = None
        self.region = REGION


_AUTH_RE = re.compile(
    r"^AWS4-HMAC-SHA256 Credential=([^/]+)/([0-9]{8})/([^/]+)/([^/]+)/aws4_request, "
    r"SignedHeaders=([^,]+), Signature=([0-9a-f]{64})$")


def _verify_sigv4(handler: http.server.BaseHTTPRequestHandler, body: bytes, inv: _Inventory) -> tuple[bool, str]:
    """An independent verifier over the request AS RECEIVED - so it proves the
    adapter signed the bytes, path and headers that really went on the wire."""
    m = _AUTH_RE.match(handler.headers.get("Authorization") or "")
    if not m:
        return False, "missing or malformed Authorization header"
    akid, date_stamp, region, service, signed, signature = m.groups()
    if akid != AKID:
        return False, "unknown access key id"
    if region != inv.region or service != "bedrock":
        return False, "credential scope mismatch"
    names = signed.split(";")
    if names != sorted(names) or "host" not in names or "x-amz-date" not in names:
        return False, "signed headers must be sorted and include host and x-amz-date"
    amz_date = handler.headers.get("x-amz-date") or ""
    if not amz_date.startswith(date_stamp):
        return False, "x-amz-date does not match credential date"
    try:
        when = datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return False, "bad x-amz-date"
    if abs((datetime.now(timezone.utc) - when).total_seconds()) > 900:
        return False, "clock skew"
    if inv.session_token:
        if "x-amz-security-token" not in names:
            return False, "session token not signed"
        if handler.headers.get("x-amz-security-token") != inv.session_token:
            return False, "session token mismatch"
    for name in names:
        if handler.headers.get(name) is None:
            return False, f"signed header {name} absent"
    canonical_headers = "".join(f"{n}:{handler.headers.get(n).strip()}\n" for n in names)
    parsed = urlsplit(handler.path)
    canonical = "\n".join([handler.command, parsed.path or "/", parsed.query, canonical_headers, signed,
                           hashlib.sha256(body).hexdigest()])
    string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, f"{date_stamp}/{region}/{service}/aws4_request",
                                hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    key = hmac.new(("AWS4" + SECRET).encode("utf-8"), date_stamp.encode("utf-8"), hashlib.sha256).digest()
    for part in (region, service, "aws4_request"):
        key = hmac.new(key, part.encode("utf-8"), hashlib.sha256).digest()
    expected = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature), "signature mismatch"


@contextmanager
def local_bedrock(inv: _Inventory):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _reply(self, status: int, obj: dict, *, retry_after: str | None = None) -> None:
            body = jsonlib.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if retry_after:
                self.send_header("Retry-After", retry_after)
            self.end_headers()
            self.wfile.write(body)

        def _read(self) -> bytes:
            return self.rfile.read(int(self.headers.get("Content-Length") or 0))

        def _record(self, body: bytes) -> dict:
            parsed = urlsplit(self.path)
            try:
                parsed_body = jsonlib.loads(body) if body else None
            except ValueError:
                parsed_body = "<not json>"
            rec = {"method": self.command, "path": parsed.path,
                   "headers": {k.lower(): v for k, v in self.headers.items()}, "body": parsed_body}
            inv.requests.append(rec)
            return rec

        def do_POST(self) -> None:
            body = self._read()
            if inv.hold_requests:
                inv.hold_event.wait(timeout=10)
            rec = self._record(body)
            # Smithy URI matching: a trailing slash is always optional.
            if rec["path"].rstrip("/") != "/agents":
                inv.non_list_calls.append(rec)
                return self._reply(404, {"message": "UnknownOperationException"})
            ok, why = _verify_sigv4(self, body, inv)
            if not ok:
                inv.signature_failures += 1
                return self._reply(403, {"message": f"The request signature we calculated does not match: {why}"})
            if inv.deny_all:
                return self._reply(403, {"message": "User is not authorized to perform: bedrock:ListAgents"})
            page_number = sum(1 for r in inv.requests if r["path"].rstrip("/") == "/agents")
            if inv.fail_page_number is not None and page_number == inv.fail_page_number:
                return self._reply(inv.fail_status, {"message": "ThrottlingException"}, retry_after="1")
            payload = rec["body"] if isinstance(rec["body"], dict) else {}
            if set(payload) - {"maxResults", "nextToken"}:
                return self._reply(400, {"message": "ValidationException: unknown field"})
            max_results = int(payload.get("maxResults", 10))
            if not 1 <= max_results <= 1000:
                return self._reply(400, {"message": "ValidationException: maxResults"})
            offset = 0
            if "nextToken" in payload:
                if payload["nextToken"] not in inv.tokens:
                    return self._reply(400, {"message": "ValidationException: invalid nextToken"})
                offset = inv.tokens[payload["nextToken"]]
            page = inv.agents[offset:offset + max_results]
            out: dict = {"agentSummaries": page}
            if offset + max_results < len(inv.agents):
                token = uuid.uuid4().hex
                inv.tokens[token] = offset + max_results
                out["nextToken"] = token
            self._reply(200, out)

        def _forbidden(self) -> None:
            body = self._read()
            inv.non_list_calls.append(self._record(body))
            self._reply(403, {"message": "AccessDeniedException"})

        do_GET = _forbidden
        do_PUT = _forbidden
        do_DELETE = _forbidden
        do_PATCH = _forbidden

        def log_message(self, *a) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _summary(agent_id: str, name: str | None = None, status: str = "PREPARED",
             description: str | None = None, version: str = "1") -> dict:
    d = {"agentId": agent_id, "agentName": name or f"agent-{agent_id}", "agentStatus": status,
         "updatedAt": "2026-09-20T10:00:00Z", "latestAgentVersion": version}
    if description:
        d["description"] = description
    return d


def _ids(n: int, prefix: str = "AG") -> list[str]:
    return [f"{prefix}{i:0{10 - len(prefix)}d}" for i in range(1, n + 1)]


def _secret(session: str | None = None) -> str:
    return f"{AKID}:{SECRET}" + (f":{session}" if session else "")


def _config(port: int, **overrides) -> dict:
    cfg = {"region": REGION, "endpoint_url": f"http://127.0.0.1:{port}", "local_dev_hosts": ["127.0.0.1"],
           "allow_plaintext_http": True, "page_size": 10, "max_pages": 5}
    cfg.update(overrides)
    return cfg


def _create_source(client: TestClient, admin: dict, port: int, *, secret: str | None = "default",
                   **overrides) -> dict:
    payload = {"name": f"Bedrock {uuid.uuid4().hex[:6]}", "adapter_key": mod.ADAPTER_KEY,
               "config": _config(port, **overrides)}
    if secret == "default":
        payload["secret"] = _secret()
    elif secret is not None:
        payload["secret"] = secret
    r = client.post(f"{DISC}/sources", headers=admin["headers"], json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _trigger(client: TestClient, admin: dict, source_id: str) -> dict:
    r = client.post(f"{DISC}/sources/{source_id}/runs", headers=admin["headers"])
    assert r.status_code == 201, r.text
    return r.json()


def _ext(agent_id: str, region: str = REGION) -> str:
    return mod.external_identifier(region, agent_id)


def _agents_by_ref(client: TestClient, admin: dict) -> dict[str, dict]:
    agents = client.get("/api/v1/runtime/agents", headers=admin["headers"]).json()
    return {a["external_reference"]: a for a in agents if a.get("external_reference")}


# =========================================================================== #
# UNIT - the 5.2 contract
# =========================================================================== #
def test_unit_adapter_is_registered_and_implements_the_5_2_contract() -> None:
    assert mod.ADAPTER_KEY in adapter_registry.registered_keys()
    adapter = adapter_registry.resolve(mod.ADAPTER_KEY)
    assert isinstance(adapter, DiscoveryAdapter)
    d = adapter.describe()
    assert d.adapter_key == mod.ADAPTER_KEY
    assert d.requires_secret is True
    assert d.config_schema["required"] == ["region"]
    assert d.config_schema["additionalProperties"] is False
    # AC-06 structural half, restated for this adapter: fetch() has no Session anywhere.
    sig = inspect.signature(adapter.fetch)
    assert set(sig.parameters) == {"client", "configuration", "secret", "checkpoint"}
    assert all("Session" not in str(p.annotation) for p in sig.parameters.values())


def test_unit_adapter_listed_by_the_api_with_its_secret_requirement(client: TestClient, admin: dict) -> None:
    r = client.get(f"{DISC}/adapters", headers=admin["headers"])
    assert r.status_code == 200
    entry = next(a for a in r.json() if a["adapter_key"] == mod.ADAPTER_KEY)
    assert entry["requires_secret"] is True
    assert "region" in entry["config_schema"]["properties"]


def test_unit_default_endpoint_is_derived_from_the_region_and_is_the_only_allowed_host() -> None:
    adapter = adapter_registry.resolve(mod.ADAPTER_KEY)
    client = adapter.build_client({"region": "eu-west-1"})
    assert isinstance(client, GovernedHttpClient)
    resolver = lambda host: ["52.0.0.1"]  # noqa: E731 - offline, deterministic, public IP
    assert client.evaluate("https://bedrock-agent.eu-west-1.amazonaws.com/agents/", resolver=resolver).allowed
    # Any other host - including another AWS region's endpoint - is denied by the allowlist alone.
    assert not client.evaluate("https://bedrock-agent.us-east-1.amazonaws.com/agents/", resolver=resolver).allowed
    assert not client.evaluate("https://evil.example.net/agents/", resolver=resolver).allowed
    # Plaintext to AWS is never allowed (allow_plaintext_http defaults to False).
    assert not client.evaluate("http://bedrock-agent.eu-west-1.amazonaws.com/agents/", resolver=resolver).allowed


@pytest.mark.parametrize("bad_region", ["evil.com/#", "us-east-1.evil.com", "US-EAST-1", "us-east", "", "us-east-1 "])
def test_unit_region_is_pattern_validated_so_the_derived_host_cannot_be_hijacked(bad_region: str) -> None:
    adapter = adapter_registry.resolve(mod.ADAPTER_KEY)
    with pytest.raises(IdentityError) as exc:
        adapter.validate_configuration({"region": bad_region})
    assert exc.value.code == ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG


def test_unit_endpoint_override_is_amazonaws_https_or_a_declared_local_dev_host_only() -> None:
    adapter = adapter_registry.resolve(mod.ADAPTER_KEY)
    adapter.validate_configuration({"region": "us-east-1"})
    adapter.validate_configuration({"region": "us-east-1",
                                    "endpoint_url": "https://bedrock-agent-fips.us-east-1.amazonaws.com"})
    adapter.validate_configuration({"region": "us-east-1", "endpoint_url": "http://127.0.0.1:9",
                                    "local_dev_hosts": ["127.0.0.1"], "allow_plaintext_http": True})
    for bad in (
        {"region": "us-east-1", "endpoint_url": "https://evil.example.net"},
        {"region": "us-east-1", "endpoint_url": "https://amazonaws.com.evil.example.net"},
        {"region": "us-east-1", "endpoint_url": "http://bedrock-agent.us-east-1.amazonaws.com"},   # plaintext to AWS
        {"region": "us-east-1", "endpoint_url": "http://127.0.0.1:9"},                              # not declared local
        {"region": "us-east-1", "endpoint_url": "https://x.amazonaws.com/some/path"},              # path prefix
        {"region": "us-east-1", "allow_plaintext_http": True},                                      # plaintext w/o local
        {"region": "us-east-1", "allowed_hosts": ["evil.example.net"]},                            # smuggled host list
        {"region": "us-east-1", "page_size": 5000},
    ):
        with pytest.raises(IdentityError) as exc:
            adapter.validate_configuration(bad)
        assert exc.value.code == ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG, bad


def test_unit_credential_format_is_parsed_and_never_echoed() -> None:
    c = mod._parse_credential(f"{AKID}:{SECRET}")
    assert (c.access_key_id, c.secret_access_key, c.session_token) == (AKID, SECRET, None)
    c2 = mod._parse_credential(f"{AKID}:{SECRET}:{SESSION}")
    assert c2.session_token == SESSION
    for bad in (None, "", "no-colon", ":", f"{AKID}:", "lowercase-akid:secret", "x" * 10 + ":" + SECRET):
        with pytest.raises(IdentityError) as exc:
            mod._parse_credential(bad)
        assert exc.value.code == ErrorCode.DISCOVERY_SOURCE_INVALID_CONFIG
        assert SECRET not in exc.value.message and AKID not in exc.value.message
        if bad and len(bad) >= 8:
            assert bad not in exc.value.message


# --------------------------------------------------------------------------- #
# UNIT - SigV4 signs exactly what the governed client transmits
# --------------------------------------------------------------------------- #
def test_unit_sigv4_body_path_and_content_type_mirror_the_governed_clients_wire_bytes() -> None:
    from app.runtime.tools.http_executor import _build_target_url

    payload = {"maxResults": 100, "nextToken": "tøkén/with+chars=="}
    url = "http://127.0.0.1:8813/agents/"
    real = httpx.Request("POST", url, json=payload)
    assert mod._encode_json_as_sent(payload) == real.content
    assert real.headers["content-type"] == mod._CONTENT_TYPE_AS_SENT
    assert real.headers["host"] == urlsplit(url).netloc == "127.0.0.1:8813"
    # The executor drops the trailing slash; the canonical URI must be what is sent.
    assert mod._path_as_sent(url) == urlsplit(_build_target_url(url, None, None)).path == "/agents"
    aws_url = "https://bedrock-agent.us-east-1.amazonaws.com/agents/"
    assert mod._path_as_sent(aws_url) == urlsplit(_build_target_url(aws_url, None, None)).path == "/agents"
    assert httpx.Request("POST", aws_url, json=payload).headers["host"] == "bedrock-agent.us-east-1.amazonaws.com"
    assert mod._path_as_sent("https://h/") == "/"


def test_unit_sigv4_matches_the_aws_sdk_signer_known_answers() -> None:
    """Known-answer vectors. Every reference value below was produced by
    botocore 1.43.66's ``SigV4Auth`` (the AWS SDK's own signer) for exactly
    these inputs, with its clock pinned, and recorded here so this test
    carries no SDK dependency. Inputs use AWS's documentation EXAMPLE keys."""
    secret = SECRET
    # 1. Signing-key derivation (date/region/service chain).
    assert mod._signing_key(secret, "20150830", "us-east-1", "iam").hex() ==         "2c94c0cf5378ada6887f09bb697df8fc0affdb34ba1cdd5bda32b664bd55b73c"
    # 2. AWS's classic IAM ListUsers example request (GET, query string, signed content-type).
    auth = mod._sigv4_authorization(
        method="GET", canonical_uri="/", canonical_query="Action=ListUsers&Version=2010-05-08",
        headers={"content-type": "application/x-www-form-urlencoded; charset=utf-8",
                 "host": "iam.amazonaws.com", "x-amz-date": "20150830T123600Z"},
        payload=b"", access_key_id="AKIDEXAMPLE", secret_access_key=secret,
        region="us-east-1", service="iam", amz_date="20150830T123600Z")
    assert auth == ("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/iam/aws4_request, "
                    "SignedHeaders=content-type;host;x-amz-date, "
                    "Signature=33f5dad2191de0cb4b7ab912f876876c2c4f72e2991a458f9499233c7b992438")
    # 3. The adapter's own request shape: ListAgents POST with a JSON body, path as sent (/agents).
    now = datetime(2026, 9, 24, 12, 0, 0, tzinfo=timezone.utc)
    body = mod._encode_json_as_sent({"maxResults": 10, "nextToken": "abc"})
    assert body == b'{"maxResults":10,"nextToken":"abc"}'
    url = "https://bedrock-agent.us-east-1.amazonaws.com/agents/"
    h = mod._signed_headers_for("POST", url, body, mod._AwsCredential(AKID, secret, None), "us-east-1", now)
    assert h["X-Amz-Date"] == "20260924T120000Z" and "X-Amz-Security-Token" not in h
    assert h["Authorization"] == (
        f"AWS4-HMAC-SHA256 Credential={AKID}/20260924/us-east-1/bedrock/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-date, "
        "Signature=413d53630f0b522672cdd9da68cadce3927f78ac5123be4c5d71e44aec55b609")
    # 4. Same request with temporary credentials: the session token is signed and sent.
    h2 = mod._signed_headers_for("POST", url, body, mod._AwsCredential(AKID, secret, SESSION), "us-east-1", now)
    assert h2["X-Amz-Security-Token"] == SESSION
    assert h2["Authorization"] == (
        f"AWS4-HMAC-SHA256 Credential={AKID}/20260924/us-east-1/bedrock/aws4_request, "
        "SignedHeaders=content-type;host;x-amz-date;x-amz-security-token, "
        "Signature=35a7bd48319ffdcc20df881585f16d4110446ee41f64ae42a7345186bea117d5")


# --------------------------------------------------------------------------- #
# UNIT - the agent-definition filter and normalization
# --------------------------------------------------------------------------- #
def test_unit_filter_includes_bedrock_agents_and_excludes_everything_else() -> None:
    for status in mod.KNOWN_AGENT_STATUSES:
        expected = status not in mod.EXCLUDED_AGENT_STATUSES
        assert mod.is_bedrock_agent(_summary("AG00000001", status=status)) is expected, status
    assert mod.EXCLUDED_AGENT_STATUSES == frozenset({"DELETING"})
    # A summary without a status is still an agent construct (status is metadata, not identity).
    assert mod.is_bedrock_agent({"agentId": "AG00000001", "agentName": "x"})
    # Not agents: other Bedrock constructs, other AWS services, malformed shapes.
    for not_agent in (
        {"knowledgeBaseId": "KB00000001", "name": "kb"},                       # knowledge base
        {"agentAliasId": "AL00000001", "agentAliasName": "prod"},              # alias (deployment pointer)
        {"agentVersion": "3", "agentName": "v"},                               # version
        {"modelId": "anthropic.claude-3", "modelName": "fm"},                  # foundation model
        {"flowId": "FL00000001", "name": "flow"},                              # flow
        {"promptId": "PR00000001", "name": "prompt"},                          # prompt
        {"guardrailId": "GR00000001", "name": "guardrail"},                    # guardrail
        {"FunctionName": "my-lambda", "FunctionArn": "arn:aws:lambda:..."},   # Lambda
        {"InstanceId": "i-0123456789abcdef0"},                                 # EC2
        {"EndpointName": "sm-endpoint"},                                       # SageMaker
        {"agentId": "not-an-id", "agentName": "x"},                            # malformed id
        {"agentId": "AG000000011", "agentName": "x"},                          # 11 chars
        {"agentId": "AG00000001"},                                             # no name
        {"agentId": "AG00000001", "agentName": ""},                            # empty name
        {"agentId": 1234567890, "agentName": "x"},                             # wrong type
        ["AG00000001"], "AG00000001", None,
    ):
        assert mod.is_bedrock_agent(not_agent) is False, not_agent


def test_unit_normalize_is_a_pure_deterministic_mapping() -> None:
    adapter = adapter_registry.resolve(mod.ADAPTER_KEY)
    summary = _summary("AG00000042", name="billing-helper", status="NOT_PREPARED",
                       description="Answers billing questions", version="DRAFT")
    item = RawDiscoveryItem(external_identifier=_ext("AG00000042"), payload={**summary, "region": REGION})
    a = adapter.normalize(item)
    b = adapter.normalize(item)
    assert a == b
    assert isinstance(a, NormalizedObservation)
    assert a.external_identifier == "bedrock-agent:us-east-1:AG00000042"
    assert a.name == "billing-helper"
    assert a.origin_provider == mod.ADAPTER_KEY and len(a.origin_provider) <= 50
    assert a.description == "Answers billing questions"
    assert a.confidence == Decimal("1.00")
    assert a.raw["agentStatus"] == "NOT_PREPARED" and a.raw["latestAgentVersion"] == "DRAFT"
    assert a.raw["region"] == REGION
    # A non-string description is dropped rather than coerced.
    odd = adapter.normalize(RawDiscoveryItem(external_identifier="x", payload={"agentName": "n", "description": 7}))
    assert odd.description is None


# =========================================================================== #
# INTEGRATION - real local server, documented wire shape, SigV4 verified
# =========================================================================== #
def test_integration_inventory_lands_as_external_discovered_agents(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary(i, description=f"agent {i}") for i in _ids(23)]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port, page_size=10, max_pages=5)
        run = _trigger(client, admin, source["id"])
    assert run["status"] == "SUCCEEDED", run
    assert run["observations_count"] == 23
    assert run["agents_created"] == 23 and run["agents_linked"] == 0 and run["findings_created"] == 0

    # Paginated over three signed ListAgents calls, nothing else, every signature valid.
    list_calls = [r for r in inv.requests if r["path"].rstrip("/") == "/agents"]
    assert len(list_calls) == 3
    assert inv.signature_failures == 0
    assert inv.non_list_calls == []
    assert {r["method"] for r in inv.requests} == {"POST"}
    assert all(set(r["body"]) <= {"maxResults", "nextToken"} for r in list_calls)
    assert "nextToken" not in list_calls[0]["body"] and "nextToken" in list_calls[1]["body"]

    by_ref = _agents_by_ref(client, admin)
    for agent_id in _ids(23):
        a = by_ref[_ext(agent_id)]
        assert a["origin_category"] == "EXTERNAL"
        assert a["origin_provider"] == mod.ADAPTER_KEY
        assert a["control_state"] == "DISCOVERED"
        assert a["name"] == f"agent-{agent_id}"
    # GOVERNED is unreachable for a cloud-discovered agent (ADR-0023, the V0.2 ruling).
    r = client.post(f"/api/v1/runtime/agents/{by_ref[_ext('AG00000001')]['id']}/control-state",
                    headers=admin["headers"], json={"target_state": "GOVERNED"})
    assert r.status_code == 409


def test_integration_only_agent_constructs_are_observed_from_a_mixed_page(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [
        _summary("AG00000001"),
        {"knowledgeBaseId": "KB00000001", "name": "kb"},
        {"agentAliasId": "AL00000001", "agentAliasName": "prod"},
        _summary("AG00000002", status="DELETING"),
        {"agentId": "bad id!!!", "agentName": "malformed"},
        _summary("AG00000003", status="FAILED"),
        "garbage", None, 42,
    ]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port)
        run = _trigger(client, admin, source["id"])
    assert run["status"] == "SUCCEEDED"
    assert run["observations_count"] == 2
    assert run["agents_created"] == 2
    by_ref = _agents_by_ref(client, admin)
    assert _ext("AG00000001") in by_ref and _ext("AG00000003") in by_ref
    assert _ext("AG00000002") not in by_ref
    db = SessionLocal()
    try:
        refs = {o.external_identifier for o in db.execute(select(DiscoveryObservation).where(
            DiscoveryObservation.source_id == uuid.UUID(source["id"]))).scalars()}
        assert refs == {_ext("AG00000001"), _ext("AG00000003")}
    finally:
        db.close()


def test_integration_rediscovery_is_idempotent(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary(i) for i in _ids(7)]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port)
        run1 = _trigger(client, admin, source["id"])
        run2 = _trigger(client, admin, source["id"])
        run3 = _trigger(client, admin, source["id"])
    assert (run1["agents_created"], run1["agents_linked"]) == (7, 0)
    assert (run2["agents_created"], run2["agents_linked"]) == (0, 7)
    assert (run3["agents_created"], run3["agents_linked"]) == (0, 7)
    assert run2["findings_created"] == 0 and run3["findings_created"] == 0
    db = SessionLocal()
    try:
        n = db.execute(select(Agent).where(Agent.organization_id == uuid.UUID(admin["organization_id"]),
                                           Agent.origin_provider == mod.ADAPTER_KEY)).scalars().all()
        assert len(n) == 7
        # Three runs -> three sets of append-only observations; nothing overwritten.
        obs = db.execute(select(DiscoveryObservation).where(
            DiscoveryObservation.source_id == uuid.UUID(source["id"]))).scalars().all()
        assert len(obs) == 21
    finally:
        db.close()


def test_integration_removed_asset_is_a_stale_finding_and_reappearance_resolves_it(
        client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary("AG00000001"), _summary("AG00000002")]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port)
        _trigger(client, admin, source["id"])
        inv.agents = [_summary("AG00000001")]          # AG00000002 removed in the cloud
        run2 = _trigger(client, admin, source["id"])
        assert run2["status"] == "SUCCEEDED" and run2["findings_created"] == 1
        by_ref = _agents_by_ref(client, admin)
        gone = by_ref[_ext("AG00000002")]
        assert gone["control_state"] == "DISCOVERED"   # a finding, never a deletion or a state change
        findings = client.get(f"{DISC}/findings", headers=admin["headers"], params={"status": "OPEN"}).json()
        stale = [f for f in findings if f["finding_type"] == "STALE_AGENT" and f["agent_id"] == gone["id"]]
        assert len(stale) == 1
        run3 = _trigger(client, admin, source["id"])   # deterministic: no second finding per miss
        assert run3["findings_created"] == 0
        inv.agents = [_summary("AG00000001"), _summary("AG00000002")]   # it is back
        _trigger(client, admin, source["id"])
    db = SessionLocal()
    try:
        f = db.get(DiscoveryFinding, uuid.UUID(stale[0]["id"]))
        assert f.status == "RESOLVED"
    finally:
        db.close()


def test_integration_outage_is_a_failed_run_never_a_deletion_or_staleness(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary("AG00000001"), _summary("AG00000002")]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port)
        _trigger(client, admin, source["id"])
    # The server is gone (connection refused) - a cloud outage.
    run = _trigger(client, admin, source["id"])
    assert run["status"] == "FAILED", run
    assert "status=None" in run["error"] and "no HTTP response" in run["error"]
    assert run["observations_count"] == 0 and run["findings_created"] == 0
    by_ref = _agents_by_ref(client, admin)
    assert by_ref[_ext("AG00000001")]["control_state"] == "DISCOVERED"
    assert by_ref[_ext("AG00000002")]["control_state"] == "DISCOVERED"
    findings = client.get(f"{DISC}/findings", headers=admin["headers"]).json()
    assert not [f for f in findings if f["finding_type"] == "STALE_AGENT"]
    # And an access denial (a revoked or mis-scoped credential) is the same shape - FAILED, nothing touched.
    inv2 = _Inventory()
    inv2.deny_all = True
    with local_bedrock(inv2) as port2:
        source2 = _create_source(client, admin, port2)
        run2 = _trigger(client, admin, source2["id"])
    assert run2["status"] == "FAILED"
    assert "status=403" in run2["error"] and "bedrock:ListAgents" in run2["error"]
    assert "Response body not recorded" in run2["error"]


def test_integration_throttled_later_page_degrades_to_partial_and_resumes(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary(i) for i in _ids(25)]
    inv.fail_page_number = 2
    inv.fail_status = 429
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port, page_size=10)
        run1 = _trigger(client, admin, source["id"])
        assert run1["status"] == "PARTIAL", run1
        assert run1["observations_count"] == 10 and run1["agents_created"] == 10
        assert "throttled" in run1["error"] and "page 2" in run1["error"]
        assert run1["checkpoint"].get("next_token")
        inv.fail_page_number = None
        inv.requests.clear()
        run2 = _trigger(client, admin, source["id"])
        assert run2["status"] == "SUCCEEDED", run2
        # Resumed from the token: the first request of run 2 carried it.
        assert inv.requests[0]["body"].get("nextToken") == run1["checkpoint"]["next_token"]
        assert run2["agents_created"] == 15 and run2["checkpoint"] == {}
    assert inv.signature_failures == 0


def test_integration_expired_resumption_token_falls_back_to_a_fresh_sweep(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary(i) for i in _ids(12)]
    inv.fail_page_number = 2
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port, page_size=10)
        run1 = _trigger(client, admin, source["id"])
        assert run1["status"] == "PARTIAL"
        inv.fail_page_number = None
        inv.tokens.clear()                       # AWS no longer knows the token
        inv.requests.clear()
        run2 = _trigger(client, admin, source["id"])
    assert run2["status"] == "SUCCEEDED", run2
    assert "nextToken" in inv.requests[0]["body"]          # tried to resume ...
    assert "nextToken" not in inv.requests[1]["body"]      # ... then started fresh
    assert run2["observations_count"] == 12 and run2["agents_linked"] == 10 and run2["agents_created"] == 2


def test_integration_temporary_credentials_sign_the_session_token(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.session_token = SESSION
    inv.agents = [_summary("AG00000001")]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port, secret=_secret(SESSION))
        run = _trigger(client, admin, source["id"])
    assert run["status"] == "SUCCEEDED", run
    assert inv.signature_failures == 0
    auth = inv.requests[0]["headers"]["authorization"]
    assert "x-amz-security-token" in auth.split("SignedHeaders=")[1].split(",")[0]


def test_integration_missing_secret_is_a_failed_run_not_a_crash(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary("AG00000001")]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port, secret=None)
        run = _trigger(client, admin, source["id"])
    assert run["status"] == "FAILED"
    assert "requires a read-only AWS credential" in run["error"]
    assert inv.requests == []                                  # nothing was sent unauthenticated


# =========================================================================== #
# NO-LOCK - the M1 deadlock discipline on the cloud path (behavioural)
# =========================================================================== #
def test_no_lock_held_across_the_cloud_call_behavioral(client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary("AG00000001")]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port)
        source_id = uuid.UUID(source["id"])
        inv.hold_requests = True
        outcome: dict = {}

        def _drive() -> None:
            outcome["response"] = client.post(f"{DISC}/sources/{source_id}/runs", headers=admin["headers"])

        t = threading.Thread(target=_drive)
        t.start()
        try:
            time.sleep(0.4)  # let the sweep reach the (held-open) cloud call
            db2 = SessionLocal()
            try:
                start = time.monotonic()
                row = db2.execute(select(DiscoverySource).where(DiscoverySource.id == source_id)
                                  .with_for_update()).scalars().first()
                assert row is not None
                row.last_run_status = "PROBE"
                db2.commit()
                elapsed = time.monotonic() - start
            finally:
                db2.close()
            assert elapsed < 2.0, (f"a concurrent FOR UPDATE on the source row took {elapsed:.2f}s while "
                                   "the cloud call was in flight - a lock is held across external I/O")
        finally:
            inv.hold_requests = False
            inv.hold_event.set()
            t.join(timeout=10)
        assert outcome["response"].status_code == 201
        assert outcome["response"].json()["status"] == "SUCCEEDED"


# =========================================================================== #
# CONTAINMENT - by construction
# =========================================================================== #
def test_containment_no_cloud_credential_in_observations_audit_runs_or_the_source_read(
        client: TestClient, admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary("AG00000001", description="api_key=sk-THISISASECRETVALUE1234567890ABCDEFGH"),
                  _summary("AG00000002", description=f"leaked {AKID} in a description")]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port, secret=_secret(SESSION))
        _trigger(client, admin, source["id"])
        inv.deny_all = True
        failed = _trigger(client, admin, source["id"])
    assert failed["status"] == "FAILED"

    db = SessionLocal()
    try:
        obs_blob = jsonlib.dumps([o.normalized_payload for o in db.execute(select(DiscoveryObservation).where(
            DiscoveryObservation.source_id == uuid.UUID(source["id"]))).scalars()])
        assert "sk-THISISASECRETVALUE1234567890ABCDEFGH" not in obs_blob
        assert AKID not in obs_blob and SECRET not in obs_blob and SESSION not in obs_blob
        assert "***REDACTED***" in obs_blob          # scrubbed by shape, not merely absent
        runs_blob = jsonlib.dumps([r.error for r in db.execute(select(DiscoveryRun).where(
            DiscoveryRun.source_id == uuid.UUID(source["id"]))).scalars()])
        assert SECRET not in runs_blob and SESSION not in runs_blob and AKID not in runs_blob
        audit_blob = jsonlib.dumps([dict(r._mapping) for r in db.execute(text(
            "SELECT meta FROM authorization_audit WHERE organization_id = :o"),
            {"o": admin["organization_id"]})], default=str)
        assert SECRET not in audit_blob and SESSION not in audit_blob and AKID not in audit_blob
        row = db.get(DiscoverySource, uuid.UUID(source["id"]))
        assert row.encrypted_secret and SECRET not in row.encrypted_secret and AKID not in row.encrypted_secret
        assert row.secret_hint == SESSION[-4:]
    finally:
        db.close()

    got = client.get(f"{DISC}/sources/{source['id']}", headers=admin["headers"]).json()
    blob = jsonlib.dumps(got)
    assert "secret" not in got and "encrypted_secret" not in got
    assert SECRET not in blob and AKID not in blob and SESSION not in blob
    # The plaintext config carries no credential material at all - by format.
    assert set(got["config"]) <= {"region", "endpoint_url", "local_dev_hosts", "allow_plaintext_http",
                                  "page_size", "max_pages"}


def test_containment_tenant_scoped_a_source_only_ever_creates_agents_in_its_own_tenant(
        client: TestClient, admin: dict, other_org_admin: dict) -> None:
    inv = _Inventory()
    inv.agents = [_summary("AG00000001")]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port)
        _trigger(client, admin, source["id"])
        # The other tenant cannot see, run, or read this source.
        assert client.get(f"{DISC}/sources/{source['id']}", headers=other_org_admin["headers"]).status_code == 404
        assert client.post(f"{DISC}/sources/{source['id']}/runs", headers=other_org_admin["headers"]).status_code == 404
    assert _ext("AG00000001") in _agents_by_ref(client, admin)
    assert _ext("AG00000001") not in _agents_by_ref(client, other_org_admin)
    db = SessionLocal()
    try:
        leaked = db.execute(select(Agent).where(
            Agent.organization_id == uuid.UUID(other_org_admin["organization_id"]),
            Agent.external_reference == _ext("AG00000001"))).scalars().first()
        assert leaked is None
    finally:
        db.close()


def test_containment_native_collision_flags_never_links(client: TestClient, admin: dict) -> None:
    r = client.post("/api/v1/runtime/agents", headers=admin["headers"], json={
        "name": "Native Colliding Agent", "description": "d", "business_purpose": "d",
        "owner_type": "USER", "owner_id": admin["user_id"], "external_reference": _ext("COLLIDE001"),
        "definition": {"name": "d", "entrypoint": "a.b:c"}})
    assert r.status_code == 201, r.text
    native_id = r.json()["id"]
    inv = _Inventory()
    inv.agents = [_summary("COLLIDE001", name="Impersonator")]
    with local_bedrock(inv) as port:
        source = _create_source(client, admin, port)
        run = _trigger(client, admin, source["id"])
    assert (run["agents_created"], run["agents_linked"], run["findings_created"]) == (0, 0, 1)
    findings = client.get(f"{DISC}/findings", headers=admin["headers"]).json()
    assert any(f["external_identifier"] == _ext("COLLIDE001") and f["agent_id"] == native_id
               and f["finding_type"] == "RECONCILIATION_AMBIGUOUS" for f in findings)
    native = client.get(f"/api/v1/runtime/agents/{native_id}", headers=admin["headers"]).json()
    assert native["control_state"] == "GOVERNED" and native["origin_category"] == "NATIVE"
    assert native["name"] == "Native Colliding Agent"     # no silent merge of the impersonator's name


# --------------------------------------------------------------------------- #
# STRUCTURAL - discovery-plane-only, one primitive, read-only, no migration
# --------------------------------------------------------------------------- #
def _module_imports() -> set[str]:
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_structural_discovery_plane_only_imports_nothing_from_threat_gateway_posture_graph_or_models() -> None:
    modules = _module_imports()
    app_imports = {m for m in modules if m == "app" or m.startswith("app.")}
    assert app_imports == {"app.discovery.adapters.base", "app.discovery.adapters.registry",
                           "app.identity.errors", "app.integration.base", "app.integration.sdk"}
    for banned in ("app.threat", "app.bridge", "app.posture", "app.graph", "app.runtime", "app.models",
                   "app.observability", "app.scheduler", "app.command_center", "app.assurance",
                   "app.discovery.service", "app.discovery.reconciliation"):
        assert not any(m == banned or m.startswith(banned + ".") for m in modules), banned


def test_structural_governed_http_client_is_the_only_network_primitive_and_no_aws_sdk() -> None:
    modules = _module_imports()
    assert "app.integration.sdk" in modules
    for banned in ("boto3", "botocore", "httpx", "requests", "urllib.request", "urllib3", "socket",
                   "aiohttp", "http.client", "ssl"):
        assert not any(m == banned or m.startswith(banned + ".") for m in modules), banned
    # boto3 is pinned in requirements for the 2.2.4 SQS queue backend; the
    # adapter neither imports nor binds it (AST above, module globals here),
    # so every byte on the wire goes through GovernedHttpClient.
    assert not any(name.startswith("boto") for name in vars(mod))
    adapter = adapter_registry.resolve(mod.ADAPTER_KEY)
    assert isinstance(adapter.build_client({"region": "us-east-1"}), GovernedHttpClient)


def test_structural_read_only_exactly_one_list_operation_and_one_iam_action() -> None:
    tree = ast.parse(_ADAPTER_PATH.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "request"]
    assert len(calls) == 1, "exactly one network call site"
    method_arg = calls[0].args[0]
    assert isinstance(method_arg, ast.Name) and method_arg.id == "LIST_AGENTS_METHOD"
    assert mod.LIST_AGENTS_METHOD == "POST" and mod.LIST_AGENTS_PATH == "/agents/"
    assert mod.REQUIRED_IAM_ACTIONS == ("bedrock:ListAgents",)
    literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not literals & {"PUT", "DELETE", "PATCH", "GET"}
    assert not any(re.search(r"bedrock:(Get|Create|Delete|Update|Prepare|Invoke|Associate|Disassociate|Tag)", s)
                   for s in literals)


def test_structural_no_migration_no_table_no_route_was_added() -> None:
    from app.core.database import Base
    from app.main import app

    versions = sorted(v.stem for v in (_BACKEND / "migrations" / "versions").glob("*.py"))
    assert versions[-1] == "0061_assurance_evidence"
    assert not any(k in name for name in Base.metadata.tables for k in ("bedrock", "cloud", "aws"))
    assert not any(k in getattr(r, "path", "") for r in app.routes for k in ("bedrock", "cloud", "aws"))


def test_structural_no_forbidden_markers_in_the_new_files() -> None:
    forbidden = ("TO" + "DO", "FIX" + "ME", "Not" + "ImplementedError",
                 "pytest.mark." + "skip", "pytest.mark." + "xfail")
    for path in (_ADAPTER_PATH, Path(__file__)):
        text_ = path.read_text(encoding="utf-8")
        assert not [t for t in forbidden if t in text_], path.name

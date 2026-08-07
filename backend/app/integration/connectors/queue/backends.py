"""Phase 2.2.4 SRS ACT-INT-FR-160, FR-162, FR-163 — the backend
abstraction: one interface over AMQP (RabbitMQ, via ``pika``) and SQS
(via the existing ``boto3`` dependency), mirroring 2.2.2's ``drivers.py``/
2.2.3's ``backends.py`` ("one small interface over per-vendor behavior")
exactly, applied to queue publish/consume instead of SQL connections or
object I/O.

**Azure Service Bus is backend-pending, not implemented.**
``azure-servicebus`` is a real dependency this environment cannot
exercise live this phase — the build prompt's own §6 explicitly allows
marking a backend pending with the abstraction ready rather than
half-implementing it, exactly 2.2.2's SQL Server / 2.2.3's Azure Blob
precedent.

**Publish size checked before any send (``ACT-INT-FR-163``).** The
payload's length is checked against the binding's effective message-size
limit before either backend is ever called — an oversized publish never
reaches the broker at all.

**Consume is bounded on both axes (``ACT-INT-FR-162``).** A batch never
exceeds ``declaration.effective_max_batch_size(binding)`` regardless of
how many messages the queue holds or what a caller asks for, and the
whole call never waits past ``effective_wait_timeout_seconds(binding)``
— each backend's own retrieval primitive (AMQP's ``basic_get``, SQS's
``receive_message``) is itself bounded, and the polling loop around it
enforces the wall-clock deadline explicitly rather than trusting either
API alone.

**Acknowledgment policy: ack-on-retrieve, explicit and identical across
backends.** A message is acknowledged (AMQP: ``basic_get(auto_ack=True)``;
SQS: an explicit ``delete_message`` call immediately after
``receive_message``) as part of the same retrieval that returns it to
the caller — the queue's perspective is that a returned message is
gone. This is a deliberate, documented choice for a bounded, discrete
tool operation (not a subscription): it is **at-most-once** from the
queue's own perspective (a crash between ack and the caller actually
using the returned batch loses those messages) — the simplest, safest
default for exactly the reason 2.2.2's row-limit and 2.2.3's read
disciplines are also "reject/return outright, never leave a system in
an ambiguous partial state." A caller that needs at-least-once or
exactly-once delivery guarantees needs a different, transactional
consumer — explicitly out of this connector's scope (§3).

**An oversized *consumed* message is truncated and flagged, not
discarded or silently passed whole.** Unlike a single-object read
(2.2.3) or a whole-result-set query (2.2.2), where "too large" fails the
entire operation, a consume call returns a *bounded batch of otherwise-
independent messages* — discarding the whole batch because one message
is oversized would defeat the point of batching, and this connector has
no redelivery mechanism to hand an oversized message back for later
(the ack already happened). So each oversized message is truncated to
the effective limit and marked ``truncated=True`` in the returned
``ConsumedMessage`` — visible, bounded, never silently whole.

**Local exceptions only.** Like 2.2.2's ``executor.py``/2.2.3's
``backends.py``, this module raises its own exception types (never
``app.integration.errors``) — translated to platform errors exclusively
by ``invoker.py``."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Mapping

from app.integration.connectors.queue.declaration import DeclaredQueueBinding, QueueDeclaration

SUPPORTED_BACKENDS = frozenset({"AMQP", "SQS"})
PENDING_BACKENDS = frozenset({"SERVICE_BUS"})

_SQS_MAX_MESSAGES_PER_CALL = 10
_SQS_MAX_WAIT_SECONDS_PER_CALL = 20
_AMQP_POLL_INTERVAL_SECONDS = 0.05


class MessageTooLargeError(Exception):
    """The payload (publish) or a retrieved message (consume, before
    truncation) exceeds the binding's effective size limit — translated
    to ``QueueMessageTooLargeError`` at the platform boundary. Only ever
    raised for *publish*; an oversized *consumed* message is truncated
    and flagged instead (see module docstring), never raised as an
    error, since one oversized message must not fail an otherwise-good
    bounded batch."""


class QueueBackendError(Exception):
    """Any other backend-level failure. The message is always a
    generic, safe summary (see ``_safe_message``) — never a raw
    driver/SDK exception's own text, which can embed a host, queue URL,
    or (for some SDK error classes) connection metadata not safe to
    surface verbatim."""


@dataclass(frozen=True, slots=True)
class ConsumedMessage:
    """One message returned by a bounded consume call. ``body`` is
    truncated to the binding's effective size limit when
    ``truncated`` is ``True`` — ``size_bytes`` always reports the
    message's *real* original size, never the truncated length, so a
    caller can tell a truncation happened and by how much."""

    body: bytes
    size_bytes: int
    truncated: bool = False


def _safe_message(exc: Exception) -> str:
    return f"{type(exc).__name__}: queue operation failed"


def _bound_message(body: bytes, max_bytes: int) -> ConsumedMessage:
    size = len(body)
    if size > max_bytes:
        return ConsumedMessage(body=body[:max_bytes], size_bytes=size, truncated=True)
    return ConsumedMessage(body=body, size_bytes=size, truncated=False)


# --------------------------------------------------------------------------- #
# AMQP (RabbitMQ, via pika)
# --------------------------------------------------------------------------- #
def _amqp_connection(declaration: QueueDeclaration, credential: Mapping[str, Any]):
    import pika

    kwargs: dict[str, Any] = {
        "host": declaration.host or "localhost", "port": declaration.port or 5672,
        "virtual_host": declaration.virtual_host or "/",
    }
    # pika.ConnectionParameters' own `credentials` default is a private
    # sentinel, not `None` -- passing `credentials=None` explicitly raises
    # a TypeError from pika itself, so the keyword is only ever included
    # when a real credential was actually resolved, letting pika fall back
    # to its own default (`guest`/`guest`) otherwise.
    if credential.get("username"):
        kwargs["credentials"] = pika.PlainCredentials(credential["username"], credential.get("password", ""))
    return pika.BlockingConnection(pika.ConnectionParameters(**kwargs))


def _amqp_publish(declaration: QueueDeclaration, binding: DeclaredQueueBinding, payload: bytes, credential) -> None:
    import pika

    try:
        connection = _amqp_connection(declaration, credential)
        try:
            channel = connection.channel()
            channel.basic_publish(exchange="", routing_key=binding.queue_name, body=payload)
        finally:
            connection.close()
    except pika.exceptions.AMQPError as exc:
        raise QueueBackendError(_safe_message(exc)) from exc


def _amqp_consume(
    declaration: QueueDeclaration, binding: DeclaredQueueBinding, credential, *,
    max_messages: int, wait_timeout_seconds: float, max_message_bytes: int,
) -> list[ConsumedMessage]:
    import pika

    messages: list[ConsumedMessage] = []
    try:
        connection = _amqp_connection(declaration, credential)
        try:
            channel = connection.channel()
            deadline = time.monotonic() + wait_timeout_seconds
            while len(messages) < max_messages and time.monotonic() < deadline:
                # `auto_ack=True` -- ack-on-retrieve, see module docstring.
                method_frame, _properties, body = channel.basic_get(queue=binding.queue_name, auto_ack=True)
                if method_frame is None:
                    # The queue has nothing available *right now* -- a short
                    # poll interval, bounded by the same deadline, rather
                    # than returning on the very first empty poll, gives a
                    # message a real chance to arrive within the window
                    # without ever blocking past it.
                    time.sleep(min(_AMQP_POLL_INTERVAL_SECONDS, max(0.0, deadline - time.monotonic())))
                    continue
                messages.append(_bound_message(body, max_message_bytes))
        finally:
            connection.close()
    except pika.exceptions.AMQPError as exc:
        raise QueueBackendError(_safe_message(exc)) from exc
    return messages


# --------------------------------------------------------------------------- #
# SQS
# --------------------------------------------------------------------------- #
def _sqs_client(declaration: QueueDeclaration, credential: Mapping[str, Any]):
    import boto3

    kwargs: dict[str, Any] = {}
    if declaration.endpoint_url:
        kwargs["endpoint_url"] = declaration.endpoint_url
    if declaration.region:
        kwargs["region_name"] = declaration.region
    # The BASIC auth scheme's generic username/password fields carry an SQS
    # access key id / secret access key -- the same deliberate reuse 2.2.3
    # established for S3 (no queue-specific field forcing a new AuthScheme).
    if credential.get("username"):
        kwargs["aws_access_key_id"] = credential["username"]
        kwargs["aws_secret_access_key"] = credential.get("password", "")
    return boto3.client("sqs", **kwargs)


def _sqs_publish(client, queue_url: str, payload: bytes) -> None:
    from botocore.exceptions import ClientError, EndpointConnectionError

    try:
        client.send_message(QueueUrl=queue_url, MessageBody=payload.decode("utf-8", errors="replace"))
    except (ClientError, EndpointConnectionError) as exc:
        raise QueueBackendError(_safe_message(exc)) from exc


def _sqs_consume(
    client, queue_url: str, *, max_messages: int, wait_timeout_seconds: float, max_message_bytes: int,
) -> list[ConsumedMessage]:
    from botocore.exceptions import ClientError, EndpointConnectionError

    messages: list[ConsumedMessage] = []
    deadline = time.monotonic() + wait_timeout_seconds
    while len(messages) < max_messages:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        batch_request = min(max_messages - len(messages), _SQS_MAX_MESSAGES_PER_CALL)
        # Ceil, not truncate: `remaining` is measured microseconds after
        # `deadline` was set, so a naive `int(remaining)` would round a
        # freshly-computed ~0.999s window down to a useless 0s long-poll.
        wait = max(0, min(-int(-remaining // 1), _SQS_MAX_WAIT_SECONDS_PER_CALL))
        try:
            response = client.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=batch_request, WaitTimeSeconds=wait)
        except (ClientError, EndpointConnectionError) as exc:
            raise QueueBackendError(_safe_message(exc)) from exc
        received = response.get("Messages", [])
        if not received:
            # Nothing available within this poll's own wait window --
            # treated as "done for now," never retried into a longer,
            # effectively-unbounded wait.
            break
        for raw_message in received:
            body = raw_message["Body"].encode("utf-8")
            messages.append(_bound_message(body, max_message_bytes))
            try:
                # Ack-on-retrieve, see module docstring -- delete happens in
                # the same call that hands the message to the caller.
                client.delete_message(QueueUrl=queue_url, ReceiptHandle=raw_message["ReceiptHandle"])
            except (ClientError, EndpointConnectionError) as exc:
                raise QueueBackendError(_safe_message(exc)) from exc
    return messages


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def publish(declaration: QueueDeclaration, binding: DeclaredQueueBinding, payload: bytes, credential: Mapping[str, Any]) -> None:
    max_bytes = declaration.effective_max_message_size_bytes(binding)
    if len(payload) > max_bytes:
        raise MessageTooLargeError(f"message exceeds the {max_bytes}-byte limit")
    if declaration.backend == "AMQP":
        _amqp_publish(declaration, binding, payload, credential)
        return
    if declaration.backend == "SQS":
        client = _sqs_client(declaration, credential)
        _sqs_publish(client, binding.queue_name, payload)
        return
    raise QueueBackendError(f"backend '{declaration.backend}' has no live implementation")


def consume(
    declaration: QueueDeclaration, binding: DeclaredQueueBinding, credential: Mapping[str, Any], *,
    max_messages: int | None = None,
) -> list[ConsumedMessage]:
    batch_cap = declaration.effective_max_batch_size(binding)
    # However many the caller asked for, the returned batch never exceeds
    # the binding's own effective cap -- a caller asking for more never
    # yields more (ACT-INT-FR-162).
    requested = batch_cap if max_messages is None else max(1, min(max_messages, batch_cap))
    timeout = declaration.effective_wait_timeout_seconds(binding)
    max_message_bytes = declaration.effective_max_message_size_bytes(binding)
    if declaration.backend == "AMQP":
        return _amqp_consume(
            declaration, binding, credential, max_messages=requested, wait_timeout_seconds=timeout,
            max_message_bytes=max_message_bytes,
        )
    if declaration.backend == "SQS":
        client = _sqs_client(declaration, credential)
        return _sqs_consume(
            client, binding.queue_name, max_messages=requested, wait_timeout_seconds=timeout,
            max_message_bytes=max_message_bytes,
        )
    raise QueueBackendError(f"backend '{declaration.backend}' has no live implementation")

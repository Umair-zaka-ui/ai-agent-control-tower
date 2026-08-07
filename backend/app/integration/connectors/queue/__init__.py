"""Phase 2.2.4 SRS ACT-INT-FR-160..164 — the generic message queue
connector, Milestone 2's fourth and last generic connector.

**Two-sided containment.** Publish is a lateral-movement/spoofing
surface — defended by scoping publish to declared queues/topics, with
the target fixed by the tool contract itself rather than a value the
model supplies (``ACT-INT-FR-161``/``FR-164``). Consume is a
resource-exhaustion/data-firehose surface — defended by bounding every
consume call to at most N messages within a bounded wait, never an
unbounded stream (``ACT-INT-FR-162``). Both by construction, both
proven with no live broker required for the security core itself.

**This is not stream processing.** No long-lived consumers, no
consumer-group/offset management, no subscriptions — a tool call is one
bounded, discrete publish or consume operation, never a reactive
process. That boundary belongs to Milestone 3's worker/scheduler system,
not this connector.

Five modules, the same split every prior generic connector established:

- ``scope.py`` — isolated, no live backend: is the requested operation
  (``PUBLISH``/``CONSUME``) permitted for a resolved binding? Simpler
  than storage's path enforcer by design — the target queue is never a
  model-supplied value to canonicalize in the first place.
- ``declaration.py`` — the config schema, per-binding declaration
  parsing, and ``tool_contracts_for``. Needed **zero** deviations from
  the SDK surface this phase (see its own module docstring for why,
  contrasting with 2.2.2's one and 2.2.3's two).
- ``backends.py`` — AMQP (RabbitMQ, via ``pika``) and SQS (via the
  existing ``boto3`` dependency) behind one dispatch interface; Azure
  Service Bus is backend-pending. Raises its own local exceptions,
  translated to platform errors by ``invoker.py`` only.
- ``connector.py`` — ``QueueConnector``, built through the SDK surface
  with zero deviations, same reason as ``declaration.py``.
- ``invoker.py`` — the tool-invocation bridge: two distinct public
  entry points, ``publish_message``/``consume_messages``, each
  double-checking the resolved binding's declared operation before
  doing anything, and auditing every attempt (reusing 2.2.3's
  ``INTEGRATION_CONNECTOR_OBJECT_ACCESSED`` event rather than adding a
  new one). Not wired into the model-driven tool loop — Milestone 1
  stays untouched."""

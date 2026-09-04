"""Phase 5.2 (M5.2) - discovery adapters: the contract, the fixed registry,
and one real reference adapter.

FUTURE PRODUCTION VENDOR ADAPTERS (Azure AI Foundry, AWS Bedrock Agents,
LangGraph/CrewAI registries, Kubernetes, a real MCP server, ...) are
explicitly deferred (SRS M5.2 §5) — this package ships exactly one,
``http_agent_registry.HttpAgentRegistryAdapter`` (``HTTP_AGENT_REGISTRY``),
which is the reference implementation the framework's own end-to-end proof
runs against, not a vendor catalog.
"""

"""Phase 5.2 (M5.2) - discovery adapters: the contract, the fixed registry,
one real reference adapter, and (since V7.5) one cloud adapter.

``http_agent_registry.HttpAgentRegistryAdapter`` (``HTTP_AGENT_REGISTRY``) is
the reference implementation the framework's own end-to-end proof runs
against. ``aws_bedrock_agents.AwsBedrockAgentsAdapter`` (``AWS_BEDROCK_AGENTS``,
ADR-0024) is the single cloud adapter the post-M5 validation programme
authorized in V7.5 so that V8 can red-team cloud discovery - discovery-plane
only, read-only, ``GovernedHttpClient`` only.

Every other vendor adapter (Azure AI Foundry, GCP Vertex AI Agent Engine,
LangGraph/CrewAI registries, Kubernetes, a real MCP server, ...) remains
explicitly deferred (SRS M5.2 §5). This package is not a vendor catalog.
"""

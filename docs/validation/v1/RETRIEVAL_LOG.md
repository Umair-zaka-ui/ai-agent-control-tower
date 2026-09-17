# V1 RETRIEVAL_LOG — every source attempted (2026-09-18)

Retrieval session: 2026-09-18, 01:27–01:56 (+05:00), Claude Code with live `WebFetch`/`WebSearch`.
Status vocabulary: **RETRIEVED** (primary page fetched and read) · **RETRIEVED (secondary)** (only a
secondary report of the primary was fetchable) · **NOT RETRIEVABLE** (URL known, fetch blocked/404) ·
**NOT FOUND** (no credible public material located). A search result alone is *not* a retrieval; rows
below marked "search only" contributed no register row unless a page was fetched.

| # | Source | URL attempted | Status | Notes |
|---|---|---|---|---|
| 1 | OWASP Top 10 for LLM Applications 2025 | https://genai.owasp.org/llm-top-10/ | RETRIEVED | edition/date and 10 entries read |
| 2 | OWASP Agentic Security Initiative | https://genai.owasp.org/initiatives/agentic-security-initiative/ | RETRIEVED | publication list read |
| 3 | OWASP Top 10 for Agentic Applications 2026 (landing) | https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ | RETRIEVED | date 2025-12-09; risk list not on landing page (PDF) |
| 4 | OWASP Top 10 for Agentic Applications 2026 (ASI01–10 list) | https://www.promptfoo.dev/docs/red-team/owasp-agentic-ai/ | RETRIEVED (secondary) | Promptfoo, dated 2026-09-17; used only for the ten names |
| 5 | OWASP GenAI LLM Top 10 2026 | https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/ | RETRIEVED | date 2026-08-03; risk list not on landing page |
| 6 | OWASP Practical Guide for Secure MCP Server Development | https://genai.owasp.org/resource/a-practical-guide-for-secure-mcp-server-development/ | RETRIEVED | 2026-02-16 |
| 7 | OWASP Agent Control Standard (ACS) | https://github.com/GenAI-Security-Project/agent-control-standard | RETRIEVED | v0.1.0/v0.1.1 |
| 8 | OWASP GenAI Exploit Round-up Q1 2026 | https://genai.owasp.org/2026/04/14/owasp-genai-exploit-round-up-report-q1-2026/ | RETRIEVED | 8 incidents |
| 9 | MITRE ATLAS matrix (web) | https://atlas.mitre.org/matrices/ATLAS · /techniques · /techniques/AML.T0051 | NOT RETRIEVABLE | HTTP 404 on all three (SPA) |
| 10 | MITRE ATLAS data (primary, machine-readable) | https://raw.githubusercontent.com/mitre-atlas/atlas-data/main/dist/ATLAS.yaml | RETRIEVED | version 5.6.0; T0086/T0110 absent from this file |
| 11 | MITRE ATLAS agent techniques T0086/T0110 | secondary via search (startupdefense.io, armosec.io) | search only | not registered as ATLAS primary; noted as unverified IDs |
| 12 | NIST AI RMF 1.0 | https://www.nist.gov/itl/ai-risk-management-framework (search) | search only | already encoded in ACT assurance frameworks; not re-fetched |
| 13 | NIST AI 100-2e2025 (AML taxonomy) | https://csrc.nist.gov/news/2025/nist-ai-100-2-adversarial-machine-learning-taxonom (search) | search only | NISTAML.015 indirect prompt injection cited via search summary |
| 14 | NIST AI Agent Standards Initiative | https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure | RETRIEVED | 2026-02-17 |
| 15 | NIST RFI summary — Security Considerations for AI Agents | https://www.nist.gov/publications/summary-analysis-responses-request-information-regarding-security-considerations-ai | RETRIEVED | 2026-05-18; abstract only |
| 16 | NIST NCCoE concept paper — agent identity & authorization | https://csrc.nist.gov/pubs/other/2026/02/05/accelerating-the-adoption-of-software-and-ai-agent/ipd | RETRIEVED | 2026-02-05, IPD |
| 17 | CISA — Careful Adoption of Agentic AI Services | https://www.cisa.gov/resources-tools/resources/careful-adoption-agentic-ai-services | RETRIEVED | 2026-05-01; landing page only |
| 18 | CERT/CC VU#221883 (CrewAI) | https://www.kb.cert.org/vuls/id/221883 | RETRIEVED | 2026-03-30 / upd 2026-05-20 |
| 19 | NSA CSI "MCP: Security Design Considerations" (PDF) | https://media.defense.gov/2026/Jun/02/2003943289/-1/-1/0/CSI_MCP_SECURITY.PDF · nsa.gov PDF · nsa.gov press release | NOT RETRIEVABLE | HTTP 403 on all three hosts |
| 20 | NSA CSI — secondary | https://www.reedsmith.com/…/nsa-publishes-security-guidance-on-designing-ai-systems-with-model-context-protoc/ | RETRIEVED (secondary) | Reed Smith 2026-06-04 |
| 21 | ENISA Threat Landscape 2025 | https://www.enisa.europa.eu/publications/enisa-threat-landscape-2025 | RETRIEVED | 2025-10-01 (upd 2026-01-09); AI content in PDF not read |
| 22 | MCP Security Best Practices (spec) | https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices | RETRIEVED | page served the 2025-11-25 revision content |
| 23 | MCP Authorization (spec 2025-11-25) | https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization | RETRIEVED | |
| 24 | MCP changelog 2025-11-25 | https://modelcontextprotocol.io/specification/2025-11-25/changelog | RETRIEVED | current revision confirmed |
| 25 | A2A specification (latest) | https://a2a-protocol.org/latest/specification/ | RETRIEVED | version 1.0.0 |
| 26 | Invariant Labs — tool poisoning | https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks | RETRIEVED | 2025-04-01 |
| 27 | CSA — MCP design-level RCE note | https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-design-rce-protocol-attack-surface-202/ | RETRIEVED | 2026-04-25 |
| 28 | OX Security — MCP supply-chain advisory | https://www.ox.security/blog/mcp-supply-chain-advisory-rce-vulnerabilities-across-the-ai-ecosystem/ | RETRIEVED | 2026-04-15 |
| 29 | Oligo — MCP Inspector CVE-2025-49596 | https://www.oligo.security/blog/critical-rce-vulnerability-in-anthropic-mcp-inspector-cve-2025-49596 | RETRIEVED | 2025-06-27 |
| 30 | mcp-remote CVE-2025-6514 | https://thehackernews.com/2025/07/critical-mcp-remote-vulnerability.html | RETRIEVED (secondary) | THN 2025-07-10 reporting JFrog |
| 31 | Unit 42 — MCP sampling attack vectors | https://unit42.paloaltonetworks.com/model-context-protocol-attack-vectors/ | RETRIEVED | 2025-12-05 |
| 32 | Unit 42 — indirect prompt injection in the wild | https://unit42.paloaltonetworks.com/ai-agent-prompt-injection/ | RETRIEVED | 2026-03-03 |
| 33 | Unit 42 — AI-enabled malware Aug 2026 | https://unit42.paloaltonetworks.com/ai-enabled-malware-analysis/ | RETRIEVED | 2026-08-25 |
| 34 | Unit 42 — Vertex AI "Double Agents" | https://unit42.paloaltonetworks.com/double-agents-vertex-ai/ | RETRIEVED | 2026-03-31 |
| 35 | Wiz — AI infrastructure honeypot telemetry | https://www.wiz.io/blog/ai-infrastructure-honeypot | RETRIEVED | 2026-08-27 |
| 36 | Wiz via eSecurityPlanet | https://www.esecurityplanet.com/news/news-litellm-mcp-server-attacks/ | NOT RETRIEVABLE | 403; superseded by #35 |
| 37 | Cyera — LangChain/LangGraph CVEs | https://www.cyera.com/research/langdrained-3-paths-to-your-data-through-the-worlds-most-popular-ai-framework | RETRIEVED | 2026-03-26 |
| 38 | OSV PYSEC-2026-397 (llama-index-core) | https://osv.dev/vulnerability/PYSEC-2026-397 | RETRIEVED | 2026-06-29 |
| 39 | OpenAI Agents SDK security advisories | https://github.com/openai/openai-agents-python/security/advisories | RETRIEVED | none published |
| 40 | Anthropic — Trustworthy agents in practice | https://www.anthropic.com/research/trustworthy-agents | RETRIEVED | 2026-04-09 |
| 41 | Anthropic — Threat intelligence report Sept 2026 | https://www.anthropic.com/threat-intelligence-report-september-2026 | RETRIEVED | Dec 2025–Aug 2026 coverage |
| 42 | OpenAI — Safety in building agents | https://developers.openai.com/api/docs/guides/agent-builder-safety | RETRIEVED | |
| 43 | OpenAI — Hugging Face incident statement | https://openai.com/index/hugging-face-model-evaluation-security-incident/ | NOT RETRIEVABLE | 403 (openai.com blocks fetch); HF primaries used |
| 44 | OpenAI — designing agents to resist prompt injection / prompt-injections post | openai.com/index/… | NOT RETRIEVABLE | same host block; search summary only |
| 45 | Hugging Face — Security Incident Disclosure July 2026 | https://huggingface.co/blog/security-incident-july-2026 | RETRIEVED | 2026-07-16 |
| 46 | Hugging Face — agent intrusion technical timeline | https://huggingface.co/blog/agent-intrusion-technical-timeline | RETRIEVED | 2026-07-27 |
| 47 | Wikipedia — 2026 OpenAI agent cyberattacks | https://en.wikipedia.org/wiki/2026_OpenAI_agent_cyberattacks | RETRIEVED (secondary) | used only to locate primaries; page metadata inconsistent (last-edit date pre-dates events) |
| 48 | Microsoft — Secure AI agents at scale (Agent 365) | https://learn.microsoft.com/en-us/security/security-for-ai/agent-365-security | RETRIEVED | ms.date 2026-04-29 |
| 49 | Microsoft — What is Entra Agent ID | https://learn.microsoft.com/en-us/entra/agent-id/what-is-microsoft-entra-agent-id | RETRIEVED | ms.date 2026-04-14, updated 2026-08-13 |
| 50 | AWS — Policy in Amazon Bedrock AgentCore | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html | RETRIEVED | no date on page |
| 51 | Google — Cloud CISO: practical guidance building with SAIF | https://cloud.google.com/blog/products/identity-security/cloud-ciso-perspectives-practical-guidance-building-with-SAIF | RETRIEVED | 2026-01-17 |
| 52 | Google — Agent Platform overview | https://docs.cloud.google.com/agent-builder/overview | RETRIEVED | no date; capability names only |
| 53 | Meta — Agents Rule of Two | https://ai.meta.com/blog/practical-ai-agent-security/ | RETRIEVED | 2025-10-31 |
| 54 | NVIDIA — Four ways to deploy more secure AI agents | https://developer.nvidia.com/blog/four-ways-to-deploy-more-secure-ai-agents/ | RETRIEVED | 2026-07-30 |
| 55 | CrowdStrike — 2026 Global Threat Report (press release) | https://www.crowdstrike.com/en-us/press-releases/2026-crowdstrike-global-threat-report/ | RETRIEVED | 2026-02-24 |
| 56 | Cisco Talos — UAT-10147 | https://blog.talosintelligence.com/uat-10147-chinese-speaking-adversary-integrates-agentic-ai-into-post-compromise-operations/ | RETRIEVED | 2026-08-20 |
| 57 | Cloudflare — Agents Week August 2026 | https://blog.cloudflare.com/agents-week-review-august-2026/ | RETRIEVED | 2026-08-10 |
| 58 | Okta — Businesses at Work 2026 | https://www.okta.com/newsroom/articles/businesses-at-work-2026/ | RETRIEVED | 2026-04-30 |
| 59 | CyberArk — AI agents and identity risks 2026 | https://www.cyberark.com/resources/blog/ai-agents-and-identity-risks-how-security-will-shift-in-2026 | NOT RETRIEVABLE | 301 to paloaltonetworks.com/blog/identity-security/ (not followed) |
| 60 | CSA — Non-Human Identity Governance Vacuum | https://labs.cloudsecurityalliance.org/research/csa-whitepaper-nonhuman-identity-agentic-ai-governance-v1-cs/ | RETRIEVED | 2026-05-20 |
| 61 | IBM — Cost of a Data Breach 2026 | https://www.ibm.com/reports/data-breach | RETRIEVED | figures partially on landing page |
| 62 | HiddenLayer — 2026 AI Threat Landscape | https://www.hiddenlayer.com/news/hiddenlayer-releases-the-2026-ai-threat-landscape-report-… | RETRIEVED | 2026-03-18 |
| 63 | Datadog — Agent Observability | https://docs.datadoghq.com/llm_observability/ (search) | search only | product docs; not registered |
| 64 | Trail of Bits / NCC agent-security research | search | NOT FOUND (this session) | no primary located in the time budget |
| 65 | ServiceNow — AI Control Tower expansion (press) | https://newsroom.servicenow.com/press-releases/details/2026/ServiceNow-expands-AI-Control-Tower-… | RETRIEVED | 2026-05-05 |
| 66 | Salesforce — Trust and Agentforce (Help) | https://help.salesforce.com/s/articleView?id=ai.copilot_trust.htm | RETRIEVED | no date shown |
| 67 | SAP — Build AI Agents on SAP BTP (Architecture Center) | https://architecture.learning.sap.com/docs/golden-path/ai-golden-path/build-and-deliver/build-ai-agents | RETRIEVED | upd 2026-04-23 |
| 68 | SAP API Policy v4/2026 §2.2.2 (primary text) | via Techzine 2026-05-13 (https://www.techzine.eu/blogs/applications/141323/…) | RETRIEVED (secondary) | primary policy document not located |
| 69 | Oracle — Fusion AI Agents secure-by-enforcement (blog) | https://blogs.oracle.com/cloud-infrastructure/fusion-ai-agents-secure-by-enforcement | NOT RETRIEVABLE | 403 |
| 70 | Oracle — AI Agent Studio readiness (docs) | https://docs.oracle.com/en/cloud/saas/readiness/common/25c/common25c/25C-common-wn-f38824.htm | RETRIEVED | access-requirement statements only |
| 71 | xAI (SpaceXAI) — Grok Bot security | https://docs.x.ai/grok-bot/security | RETRIEVED | page self-identifies publisher as "Cursor (Anysphere)"; recorded as-is |
| 72 | xAI (SpaceXAI) — Enterprise deployments | https://docs.x.ai/build/enterprise | RETRIEVED | |
| 73 | SpaceX — AI/agent security technical documentation | search | NOT FOUND | only unrelated account-compromise and Starlink items |
| 74 | Mexican government breach (Dec 2025–Feb 2026) | via OWASP round-up (#8) and UpGuard/SC Media (search) | RETRIEVED (via #8) | primary Anthropic statement not fetchable (host block) |
| 75 | Vertex AI "Double Agent" (Google bulletin) | https://docs.cloud.google.com/vertex-ai/docs/security-bulletins (search) | search only | Unit 42 primary (#34) used |
| 76 | Google security summit March 2026 (AI Protection) | search | search only | not fetched |
| 77 | ATLAS SAFE-AI framework PDF | https://atlas.mitre.org/pdf-files/SAFEAI_Full_Report.pdf (search) | search only | not fetched |

Totals: attempted **77**; RETRIEVED (primary) **47**; RETRIEVED (secondary) **6**; NOT RETRIEVABLE **8**;
NOT FOUND **2**; search-only (no register row unless corroborated) **14**.

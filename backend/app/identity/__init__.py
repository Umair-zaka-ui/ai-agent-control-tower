"""Enterprise Identity Platform (EIP) — Phase 4 Part 4.1.

An isolated identity foundation: every human, AI agent, service account,
organization and external application has a formal identity model with a
consistent lifecycle. This package must not import agent/business code — the
dependency flows the other way (the rest of the platform depends on identity).

Layering (SRS §13): api → services → repositories → database.
"""

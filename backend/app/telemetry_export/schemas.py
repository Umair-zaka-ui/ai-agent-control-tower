"""Request/response schemas for the export management API (Phase 4.6 §6)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class ExportConfigWrite(BaseModel):
    """The per-environment ``telemetry_export`` block a manager may set.

    Only these four fields -- buffer sizing and timeouts are platform-level, not
    a tenant knob (see ``docs/observability/opentelemetry.md``)."""

    environment_id: uuid.UUID
    enabled: bool = False
    endpoint: str = ""
    protocol: str = Field(default="otlp-http")
    headers: dict[str, str] = Field(default_factory=dict)

    def as_block(self) -> dict:
        return {
            "enabled": self.enabled,
            "endpoint": self.endpoint,
            "protocol": self.protocol,
            "headers": self.headers,
        }


class ExportConfigRead(BaseModel):
    environment_id: str
    environment_name: str
    stored_block: dict | None
    effective: dict


class ExporterHealthRead(BaseModel):
    exporter: dict
    platform_default: dict

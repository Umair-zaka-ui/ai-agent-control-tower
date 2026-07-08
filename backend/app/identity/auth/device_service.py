"""DeviceService — register, recognise, trust and block devices (SRS §13, §14).

A device is identified by a **fingerprint** derived from stable characteristics of
the client. The fingerprint is computed from client-supplied data (User-Agent, an
optional ``X-Device-Id`` header), so it can be forged. It is therefore used to
*recognise* a device for UX and risk scoring — never as an authentication factor
on its own. A blocked device is a hard stop; a trusted device only lowers risk.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.identity.models.enums import DeviceStatus
from app.identity.models.session import UserDevice
from app.identity.repositories.device_repository import DeviceRepository


@dataclass(frozen=True)
class ClientInfo:
    """What we could learn about the caller's device from one request."""

    fingerprint: str
    device_name: str | None
    device_type: str  # desktop | mobile | tablet | bot | unknown
    browser: str | None
    browser_version: str | None
    operating_system: str | None


# Ordered most-specific first: Edge advertises "Chrome", Chrome advertises
# "Safari". Matching in this order avoids the classic mislabelling.
_BROWSERS: tuple[tuple[str, str], ...] = (
    ("Edg", "Edge"),
    ("OPR", "Opera"),
    ("Firefox", "Firefox"),
    ("Chrome", "Chrome"),
    ("Safari", "Safari"),
)

_OPERATING_SYSTEMS: tuple[tuple[str, str], ...] = (
    ("Windows NT 10", "Windows 10/11"),
    ("Windows", "Windows"),
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Android", "Android"),
    ("Mac OS X", "macOS"),
    ("Linux", "Linux"),
)


def parse_user_agent(user_agent: str | None) -> ClientInfo:
    """Best-effort UA parsing with no third-party dependency.

    Deliberately small: we need a human-readable label for the session list, not
    a forensic UA database. Unrecognised clients degrade to ``unknown`` rather
    than guessing.
    """
    ua = user_agent or ""

    browser = version = None
    for token, name in _BROWSERS:
        match = re.search(rf"{re.escape(token)}/([\d.]+)", ua)
        if match:
            browser, version = name, match.group(1).split(".")[0]
            break

    operating_system = next((name for token, name in _OPERATING_SYSTEMS if token in ua), None)

    lowered = ua.lower()
    if any(token in lowered for token in ("bot", "crawler", "spider", "curl", "python-requests")):
        device_type = "bot"
    elif "ipad" in lowered or "tablet" in lowered:
        device_type = "tablet"
    elif "mobi" in lowered or "iphone" in lowered or "android" in lowered:
        device_type = "mobile"
    elif ua:
        device_type = "desktop"
    else:
        device_type = "unknown"

    if browser and operating_system:
        device_name = f"{browser} on {operating_system}"
    elif operating_system:
        device_name = operating_system
    elif browser:
        device_name = browser
    else:
        device_name = None

    return ClientInfo(
        fingerprint="",  # filled by ``fingerprint_for``
        device_name=device_name,
        device_type=device_type,
        browser=browser,
        browser_version=version,
        operating_system=operating_system,
    )


def fingerprint_for(user_agent: str | None, device_id_header: str | None = None) -> str:
    """Stable per-device identifier.

    If the client supplies an ``X-Device-Id`` we trust it *for identification only*
    — it lets one browser stay one device across UA version bumps. Otherwise we
    fall back to a coarse hash of the parsed UA (not the raw UA, so a Chrome patch
    release does not register a "new device" every week).
    """
    if device_id_header:
        material = f"did:{device_id_header.strip()}"
    else:
        info = parse_user_agent(user_agent)
        material = f"ua:{info.browser}|{info.operating_system}|{info.device_type}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class DeviceService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = DeviceRepository(db)

    # ------------------------------------------------------------------ #
    # Registration (SRS §13)
    # ------------------------------------------------------------------ #
    def register_or_touch(
        self,
        user_id: uuid.UUID,
        *,
        user_agent: str | None,
        ip_address: str | None,
        device_id_header: str | None = None,
    ) -> tuple[UserDevice, bool]:
        """Upsert the device for this login. Returns ``(device, is_new)``.

        ``is_new`` drives both the "new device" security-score penalty and the
        new-device notification, so it must mean *first time we have ever seen
        this device for this user* — not "first time this session".
        """
        fingerprint = fingerprint_for(user_agent, device_id_header)
        now = datetime.now(timezone.utc)
        device = self.repo.get_by_fingerprint(user_id, fingerprint)

        if device is not None:
            device.last_ip = ip_address or device.last_ip
            device.last_seen_at = now
            self.db.flush()
            return device, False

        info = parse_user_agent(user_agent)
        device = UserDevice(
            user_id=user_id,
            fingerprint=fingerprint,
            device_name=info.device_name,
            device_type=info.device_type,
            browser=info.browser,
            browser_version=info.browser_version,
            operating_system=info.operating_system,
            status=DeviceStatus.UNKNOWN.value,
            last_ip=ip_address,
            last_seen_at=now,
            created_at=now,
        )
        return self.repo.add(device), True

    # ------------------------------------------------------------------ #
    # Trust posture (SRS §14)
    # ------------------------------------------------------------------ #
    def trust(self, device: UserDevice) -> UserDevice:
        device.status = DeviceStatus.TRUSTED.value
        self.db.flush()
        return device

    def block(self, device: UserDevice) -> UserDevice:
        device.status = DeviceStatus.BLOCKED.value
        self.db.flush()
        return device

    def untrust(self, device: UserDevice) -> UserDevice:
        device.status = DeviceStatus.UNKNOWN.value
        self.db.flush()
        return device

    def list_for_user(self, user_id: uuid.UUID) -> list[UserDevice]:
        return self.repo.list_for_user(user_id)

    def get_for_user(self, user_id: uuid.UUID, device_id: uuid.UUID) -> UserDevice | None:
        """Scoped lookup — a user may never address another user's device."""
        device = self.repo.get(device_id)
        if device is None or device.user_id != user_id:
            return None
        return device

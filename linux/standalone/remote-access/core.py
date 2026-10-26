"""Базовая модель temporary-share без привязки к конкретному проекту."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import hashlib
import hmac
import secrets
from urllib.parse import quote


class ShareKind(StrEnum):
    """Разрешённые типы временного доступа."""

    REMOTE_ACCESS = "remote_access"
    SECRET_INTAKE = "secret_intake"


class ShareState(StrEnum):
    """Состояние заявки в broker-хранилище."""

    OPEN = "open"
    REVOKED = "revoked"
    CONSUMED = "consumed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ShareRecord:
    """Несеcret-метаданные заявки, которые допустимо хранить."""

    share_id: str
    token_hash: str
    kind: ShareKind
    created_at: datetime
    expires_at: datetime
    state: ShareState = ShareState.OPEN

    def is_expired(self, now: datetime | None = None) -> bool:
        """Проверяет срок действия в UTC, не меняя состояние записи."""
        current = now or datetime.now(timezone.utc)
        return current >= self.expires_at


def generate_token() -> str:
    """Создаёт bearer-токен, пригодный для URL; токен не журналируется ядром."""
    return secrets.token_urlsafe(32)


def hash_token(token: str, pepper: bytes) -> str:
    """Возвращает детерминированный HMAC-хэш токена для хранения в БД."""
    if not token or not pepper:
        raise ValueError("token and pepper are required")
    return hmac.new(pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()


def clamp_ttl(ttl_seconds: int, maximum_seconds: int = 1800) -> int:
    """Ограничивает TTL серверным максимумом и отбрасывает невалидные значения."""
    if maximum_seconds <= 0:
        raise ValueError("maximum_seconds must be positive")
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    return min(ttl_seconds, maximum_seconds)


def new_expiry(ttl_seconds: int, maximum_seconds: int = 1800) -> datetime:
    """Вычисляет абсолютный expiry timestamp в UTC."""
    return datetime.now(timezone.utc) + timedelta(
        seconds=clamp_ttl(ttl_seconds, maximum_seconds)
    )


def build_public_url(base_url: str, route: str, token: str) -> str:
    """Строит ссылку capability-share без query-параметров."""
    base = base_url.rstrip("/")
    clean_route = "/" + route.strip("/")
    if not base or not token:
        raise ValueError("base_url and token are required")
    return f"{base}{clean_route}/{quote(token, safe='')}"

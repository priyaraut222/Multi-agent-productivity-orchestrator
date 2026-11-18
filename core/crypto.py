"""Symmetric encryption for stored OAuth tokens and API keys (Fernet, free & local)."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from core import config


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(config.APP_SECRET.encode()).digest())
    return Fernet(key)


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None

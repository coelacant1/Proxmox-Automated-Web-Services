"""AES-256-GCM encryption for storing secrets in the database.

Master key is read from PAWS_MASTER_KEY env var. If not set, a key is
auto-generated and persisted to a local file on first use.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger(__name__)

_NONCE_BYTES = 12
_KEY_BYTES = 32  # 256 bits
_KEY_FILE = Path("/data/.paws_master_key")
_master_key: bytes | None = None


def _resolve_master_key() -> bytes:
    """Return the 32-byte master key, creating one if necessary."""
    global _master_key
    if _master_key is not None:
        return _master_key

    env_key = os.environ.get("PAWS_MASTER_KEY", "").strip()
    if env_key:
        raw = base64.urlsafe_b64decode(env_key)
        if len(raw) != _KEY_BYTES:
            raise ValueError(f"PAWS_MASTER_KEY must decode to {_KEY_BYTES} bytes, got {len(raw)}")
        _master_key = raw
        return _master_key

    # Try reading from persistent file
    if _KEY_FILE.exists():
        raw = base64.urlsafe_b64decode(_KEY_FILE.read_text().strip())
        if len(raw) == _KEY_BYTES:
            _master_key = raw
            log.info("Loaded master key from %s", _KEY_FILE)
            return _master_key

    # Auto-generate and persist
    _master_key = secrets.token_bytes(_KEY_BYTES)
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(base64.urlsafe_b64encode(_master_key).decode())
        _KEY_FILE.chmod(0o600)
        log.info("Generated and saved new master key to %s", _KEY_FILE)
    except OSError:
        # Fallback: write to working directory
        fallback = Path(".paws_master_key")
        fallback.write_text(base64.urlsafe_b64encode(_master_key).decode())
        fallback.chmod(0o600)
        log.warning("Could not write to %s, saved master key to %s", _KEY_FILE, fallback)

    return _master_key


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return a base64-encoded ciphertext.

    Format: base64(nonce || ciphertext_with_tag)
    """
    key = _resolve_master_key()
    nonce = secrets.token_bytes(_NONCE_BYTES)
    aesgcm = AESGCM(key)
    ct = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt(token: str) -> str:
    """Decrypt a base64-encoded token back to plaintext."""
    key = _resolve_master_key()
    raw = base64.urlsafe_b64decode(token)
    if len(raw) < _NONCE_BYTES + 1:
        raise ValueError("Invalid encrypted token")
    nonce = raw[:_NONCE_BYTES]
    ct = raw[_NONCE_BYTES:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ct, None).decode("utf-8")


def generate_master_key() -> str:
    """Generate a new base64-encoded master key (for CLI/setup tooling)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(_KEY_BYTES)).decode("ascii")


def mask_secret(value: str, visible: int = 4) -> str:
    """Mask a secret string, showing only the last N characters."""
    if len(value) <= visible:
        return "*" * len(value)
    return "*" * (len(value) - visible) + value[-visible:]

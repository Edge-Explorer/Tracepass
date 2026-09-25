"""Session Persistence Manager for Tracepass.

Implements Section 5 & Decision 3 of docs/login-engine.md:
- Persists session state to ~/.tracepass/sessions/<sha256_of_domain>.json.
- Restricts file permissions (chmod 600 / owner read-write only).
- Captures cookies, localStorage, and sessionStorage.
- Provides session validation, loading, saving, and invalidation.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages secure serialization and lifecycle of authenticated browser sessions."""

    DEFAULT_SESSIONS_DIR = Path.home() / ".tracepass" / "sessions"

    def __init__(self, storage_dir: Path | None = None) -> None:
        self.storage_dir = storage_dir or self.DEFAULT_SESSIONS_DIR
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Creates the session directory with secure directory permissions."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":  # POSIX systems
            with contextlib.suppress(OSError):
                os.chmod(self.storage_dir, 0o700)

    @classmethod
    def normalize_domain(cls, domain_or_url: str) -> str:
        """Normalizes a URL or domain string into a standard lowercase hostname.

        Uses scheme + host parsing (e.g. 'https://sub.Example.com:443/login' -> 'sub.example.com').
        """
        raw = domain_or_url.strip()
        if "://" not in raw:
            raw = f"https://{raw}"
        parsed = urlparse(raw)
        hostname = (parsed.hostname or parsed.netloc).lower()
        return hostname

    def get_session_path(self, domain_or_url: str) -> Path:
        """Computes ~/.tracepass/sessions/<sha256_of_domain>.json for a domain."""
        normalized = self.normalize_domain(domain_or_url)
        domain_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self.storage_dir / f"{domain_hash}.json"

    def has_valid_session(self, domain_or_url: str, max_age_seconds: int = 86400 * 7) -> bool:
        """Checks if an unexpired session file exists for the specified domain."""
        session_path = self.get_session_path(domain_or_url)
        if not session_path.is_file():
            return False

        try:
            data = json.loads(session_path.read_text(encoding="utf-8"))
            created_at = data.get("created_at", 0)
            # Check expiry age
            if time.time() - created_at > max_age_seconds:
                logger.info("Session expired for %s", domain_or_url)
                return False
            # Ensure at least one cookie exists
            return bool(data.get("cookies"))
        except Exception as e:
            logger.warning("Error reading session file %s: %s", session_path, e)
            return False

    def load_session(self, domain_or_url: str) -> dict[str, Any] | None:
        """Loads and returns the session dictionary from disk, or None if missing."""
        session_path = self.get_session_path(domain_or_url)
        if not session_path.is_file():
            return None

        try:
            return json.loads(session_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("Failed to parse session file %s: %s", session_path, e)
            return None

    def save_session(
        self,
        domain_or_url: str,
        cookies: list[dict[str, Any]],
        session_storage: dict[str, Any] | None = None,
        local_storage: dict[str, Any] | None = None,
    ) -> Path:
        """Atomically saves the session payload to disk with chmod 600 permissions."""
        normalized = self.normalize_domain(domain_or_url)
        session_path = self.get_session_path(normalized)

        payload = {
            "domain": normalized,
            "created_at": time.time(),
            "cookies": cookies,
            "session_storage": session_storage or {},
            "local_storage": local_storage or {},
        }

        # Atomic write: write to tempfile first, then rename
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.storage_dir,
            delete=False,
            encoding="utf-8",
        ) as temp_file:
            json.dump(payload, temp_file, indent=2)
            temp_file_name = temp_file.name

        try:
            # Restrict file permissions to owner read/write (chmod 600)
            if os.name != "nt":
                with contextlib.suppress(OSError):
                    os.chmod(temp_file_name, 0o600)

            # Atomic replace
            os.replace(temp_file_name, session_path)
            logger.info("Saved session for %s to %s", normalized, session_path.name)
            return session_path
        finally:
            if os.path.exists(temp_file_name):
                with contextlib.suppress(OSError):
                    os.remove(temp_file_name)

    def invalidate_session(self, domain_or_url: str) -> bool:
        """Deletes the saved session file for a domain when logout/expiry is detected."""
        session_path = self.get_session_path(domain_or_url)
        if session_path.is_file():
            try:
                session_path.unlink()
                logger.info("Invalidated session for %s", domain_or_url)
                return True
            except OSError as e:
                logger.error("Failed to delete session file %s: %s", session_path, e)
                return False
        return False

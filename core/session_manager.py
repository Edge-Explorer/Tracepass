"""Session Persistence Manager for Tracepass.

Implements Section 5 & Decision 3 of docs/login-engine.md:
- Persists session state to ~/.tracepass/sessions/<sha256_of_domain>.json.
- Restricts file permissions (chmod 600 / owner read-write only on POSIX and restricted ACL on Windows).
- Captures cookies, localStorage, and sessionStorage.
- Provides session validation, loading, saving, and invalidation.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import subprocess
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
        else:
            # Enforce restricted Windows ACL: remove inheritance and grant current user full control
            with contextlib.suppress(Exception):
                username = os.environ.get("USERNAME", "")
                if username:
                    subprocess.run(
                        [
                            "icacls",
                            str(self.storage_dir),
                            "/inheritance:r",
                            "/grant:r",
                            f"{username}:(OI)(CI)F",
                        ],
                        check=False,
                        capture_output=True,
                    )

    @classmethod
    def normalize_origin(cls, domain_or_url: str) -> str:
        """Normalizes a URL or domain string into a standard scheme + host[:port] origin.

        Distinguishes http vs https and port numbers (e.g. 'http://example.com:8080' vs 'https://example.com').
        """
        raw = domain_or_url.strip()
        if "://" not in raw:
            raw = f"https://{raw}"
        parsed = urlparse(raw)
        scheme = (parsed.scheme or "https").lower()
        netloc = (parsed.netloc or parsed.path).lower()
        return f"{scheme}://{netloc}"

    @classmethod
    def normalize_domain(cls, domain_or_url: str) -> str:
        """Backward-compatible alias for origin normalization."""
        return cls.normalize_origin(domain_or_url)

    def get_session_path(self, domain_or_url: str) -> Path:
        """Computes ~/.tracepass/sessions/<sha256_of_domain>.json for a domain or origin."""
        normalized = self.normalize_origin(domain_or_url)
        origin_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return self.storage_dir / f"{origin_hash}.json"

    def has_valid_session(self, domain_or_url: str, max_age_seconds: int = 86400 * 7) -> bool:
        """Checks if an unexpired session file exists with valid cookies or storage state."""
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

            # Accept session if cookies, localStorage, or sessionStorage contains auth data
            has_cookies = bool(data.get("cookies"))
            has_storage = bool(data.get("local_storage")) or bool(data.get("session_storage"))
            return has_cookies or has_storage
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
        normalized = self.normalize_origin(domain_or_url)
        session_path = self.get_session_path(normalized)

        payload = {
            "domain": normalized,
            "created_at": time.time(),
            "cookies": cookies,
            "session_storage": session_storage or {},
            "local_storage": local_storage or {},
        }

        # Safe atomic write: enclose temporary file lifecycle in try-finally
        temp_file_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.storage_dir,
                delete=False,
                encoding="utf-8",
            ) as temp_file:
                temp_file_name = temp_file.name
                json.dump(payload, temp_file, indent=2)

            # Restrict file permissions to owner read/write (chmod 600)
            if os.name != "nt":
                with contextlib.suppress(OSError):
                    os.chmod(temp_file_name, 0o600)

            # Atomic replace
            os.replace(temp_file_name, session_path)
            logger.info("Saved session for %s to %s", normalized, session_path.name)
            return session_path
        finally:
            if temp_file_name and os.path.exists(temp_file_name):
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

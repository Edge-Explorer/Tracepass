"""Credential Manager (Component B).

Implements Section 4 & Decision 4 of docs/login-engine.md:
- Resolves credentials in memory without passing them to LLMs or plain logs.
- Supports TRACEPASS_CREDS environment variable injection for automated CI.
- Supports OS Keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service).
- Provides an AES-256-GCM encrypted fallback vault (Decision 4 specification).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

try:
    import keyring
except ImportError:
    keyring = None  # Graceful fallback if keyring library is not installed


class CredentialNotFound(Exception):
    """Raised when no credentials are found for the requested domain."""


class DecryptionError(Exception):
    """Raised when decryption of the encrypted credential vault fails (invalid password or corrupted data)."""


class InvalidVaultFormat(Exception):
    """Raised when the credential vault structure violates the Decision 4 format specification."""


class CredentialManager:
    """Resolves and securely stores authentication credentials for Tracepass."""

    DEFAULT_VAULT_PATH = Path.home() / ".tracepass" / "credentials.enc"
    KEYRING_SERVICE_NAME = "tracepass"
    PBKDF2_ITERATIONS = 600_000

    def __init__(
        self,
        vault_path: Path | None = None,
        master_password: str | None = None,
    ) -> None:
        """Initializes CredentialManager.

        Args:
            vault_path: Optional custom path for the encrypted credentials file.
            master_password: Optional master password to unlock the encrypted vault.
        """
        self.vault_path = vault_path or self.DEFAULT_VAULT_PATH
        self.master_password = master_password
        self._memory_cache: dict[str, tuple[str, str]] = {}

    @staticmethod
    def normalize_domain(domain_or_url: str) -> str:
        """Normalizes a domain or URL to a clean lowercase hostname.

        Examples:
            'https://Discord.com/login' -> 'discord.com'
            'sub.domain.org:8080' -> 'sub.domain.org'
        """
        clean = domain_or_url.strip().lower()
        if "://" in clean:
            clean = urlparse(clean).netloc
        clean = clean.split("/", 1)[0].split(":", 1)[0]
        return clean

    def inject_credentials(self, domain: str, username: str, password: str) -> None:
        """Injects credentials directly into process memory (for programmatic testing)."""
        norm_domain = self.normalize_domain(domain)
        self._memory_cache[norm_domain] = (username, password)

    def get_credentials(self, domain_or_url: str) -> tuple[str, str] | None:
        """Resolves username and password for a domain across all configured sources.

        Priority order:
        1. In-process memory cache.
        2. TRACEPASS_CREDS environment variable (JSON map).
        3. OS Keyring (if available).
        4. Encrypted vault file (~/.tracepass/credentials.enc).

        Returns:
            tuple[str, str] | None: (username, password) or None if not found.
        """
        norm_domain = self.normalize_domain(domain_or_url)

        # 1. In-process memory cache
        if norm_domain in self._memory_cache:
            return self._memory_cache[norm_domain]

        # 2. TRACEPASS_CREDS environment variable (JSON string)
        env_creds_raw = os.environ.get("TRACEPASS_CREDS")
        if env_creds_raw:
            try:
                env_map = json.loads(env_creds_raw)
                for key, val in env_map.items():
                    if self.normalize_domain(key) == norm_domain:
                        user = val.get("username")
                        pwd = val.get("password")
                        if user and pwd:
                            return (user, pwd)
            except Exception as e:
                logger.warning("Failed to parse TRACEPASS_CREDS environment variable: %s", e)

        # 3. OS Keyring
        if keyring is not None:
            with contextlib.suppress(Exception):
                raw = keyring.get_password(self.KEYRING_SERVICE_NAME, norm_domain)
                if raw:
                    data = json.loads(raw)
                    user = data.get("username")
                    pwd = data.get("password")
                    if user and pwd:
                        return (user, pwd)

        # 4. Encrypted Vault File
        if self.vault_path.is_file() and self.master_password:
            try:
                vault_data = self.read_encrypted_vault(self.master_password)
                if norm_domain in vault_data:
                    record = vault_data[norm_domain]
                    return (record["username"], record["password"])
            except Exception as e:
                logger.warning("Error reading encrypted vault for %s: %s", norm_domain, e)

        return None

    def read_encrypted_vault(self, master_password: str) -> dict[str, dict[str, str]]:
        """Reads and decrypts the AES-256-GCM encrypted vault file.

        Implements Decision 4 format verification:
        - version == 1
        - 16-byte salt, 12-byte nonce, 16-byte tag.
        """
        if not self.vault_path.is_file():
            return {}

        try:
            record = json.loads(self.vault_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise InvalidVaultFormat(f"Vault file {self.vault_path} is not valid JSON") from e

        if record.get("version") != 1:
            raise InvalidVaultFormat(f"Unsupported vault version: {record.get('version')}")

        try:
            salt = bytes.fromhex(record["salt"])
            nonce = bytes.fromhex(record["nonce"])
            tag = bytes.fromhex(record["tag"])
            ciphertext = bytes.fromhex(record["ciphertext"])
        except Exception as e:
            raise InvalidVaultFormat("Vault record contains non-hex fields") from e

        if len(salt) != 16 or len(nonce) != 12 or len(tag) != 16:
            raise InvalidVaultFormat(
                f"Invalid field lengths in vault: salt={len(salt)}B, nonce={len(nonce)}B, tag={len(tag)}B"
            )

        # Derive AES-256 key via PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )
        key = kdf.derive(master_password.encode("utf-8"))

        # Decrypt with AES-256-GCM and verify tag
        aesgcm = AESGCM(key)
        try:
            decrypted_bytes = aesgcm.decrypt(nonce, ciphertext + tag, None)
            return json.loads(decrypted_bytes.decode("utf-8"))
        except Exception as e:
            raise DecryptionError(
                "Failed to decrypt vault: invalid master password or corrupted tag"
            ) from e

    def save_to_encrypted_vault(
        self,
        domain: str,
        username: str,
        password: str,
        master_password: str,
    ) -> None:
        """Encrypts and atomically saves credentials to the Decision 4 fallback vault."""
        norm_domain = self.normalize_domain(domain)
        current_data: dict[str, dict[str, str]] = {}

        if self.vault_path.is_file():
            current_data = self.read_encrypted_vault(master_password)

        current_data[norm_domain] = {"username": username, "password": password}
        plaintext_bytes = json.dumps(current_data).encode("utf-8")

        # Generate fresh random salt (16B) and nonce (12B) per write
        salt = os.urandom(16)
        nonce = os.urandom(12)

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.PBKDF2_ITERATIONS,
        )
        key = kdf.derive(master_password.encode("utf-8"))

        aesgcm = AESGCM(key)
        encrypted_payload = aesgcm.encrypt(nonce, plaintext_bytes, None)
        ciphertext = encrypted_payload[:-16]
        tag = encrypted_payload[-16:]

        record: dict[str, Any] = {
            "version": 1,
            "salt": salt.hex(),
            "nonce": nonce.hex(),
            "tag": tag.hex(),
            "ciphertext": ciphertext.hex(),
        }

        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        temp_file_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.vault_path.parent,
                delete=False,
                encoding="utf-8",
            ) as temp_file:
                temp_file_name = temp_file.name
                json.dump(record, temp_file, indent=2)

            if os.name != "nt":
                with contextlib.suppress(OSError):
                    os.chmod(temp_file_name, 0o600)

            os.replace(temp_file_name, self.vault_path)
            logger.info(
                "Saved encrypted credentials for %s to %s", norm_domain, self.vault_path.name
            )
        finally:
            if temp_file_name and os.path.exists(temp_file_name):
                with contextlib.suppress(OSError):
                    os.remove(temp_file_name)

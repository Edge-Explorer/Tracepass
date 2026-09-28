"""Tests for Credential Manager (Component B)."""

import json
from pathlib import Path

import pytest

from core.credential_manager import (
    CredentialManager,
    DecryptionError,
    InvalidVaultFormat,
)


def test_domain_normalization():
    """Verify domain normalization strips scheme, path, and port."""
    assert CredentialManager.normalize_domain("https://Discord.com/login") == "discord.com"
    assert (
        CredentialManager.normalize_domain("http://Sub.Domain.org:8080/path?q=1")
        == "sub.domain.org"
    )
    assert CredentialManager.normalize_domain("reddit.com") == "reddit.com"


def test_env_injected_credentials(monkeypatch: pytest.MonkeyPatch):
    """Verify credentials resolved from TRACEPASS_CREDS environment variable."""
    creds_payload = {
        "example.com": {"username": "test_user", "password": "env_password_123"},
        "github.com": {"username": "git_user", "password": "secret_github_token"},
    }
    monkeypatch.setenv("TRACEPASS_CREDS", json.dumps(creds_payload))

    manager = CredentialManager()
    resolved = manager.get_credentials("https://example.com/login")
    assert resolved == ("test_user", "env_password_123")

    resolved_git = manager.get_credentials("github.com")
    assert resolved_git == ("git_user", "secret_github_token")

    assert manager.get_credentials("unknown.org") is None


def test_encrypted_vault_save_and_read(tmp_path: Path):
    """Verify Decision 4 AES-256-GCM encrypted vault serialization and roundtrip."""
    vault_file = tmp_path / "credentials.enc"
    manager = CredentialManager(vault_path=vault_file, master_password="secure_master_password_99")

    manager.save_to_encrypted_vault(
        domain="reddit.com",
        username="reddit_user",
        password="reddit_password_456",
        master_password="secure_master_password_99",
    )

    assert vault_file.is_file()

    # Inspect on-disk JSON structure
    data = json.loads(vault_file.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["salt"]) == 32  # 16 bytes hex
    assert len(data["nonce"]) == 24  # 12 bytes hex
    assert len(data["tag"]) == 32  # 16 bytes hex
    assert "reddit_user" not in json.dumps(data)  # Plaintext never on disk

    # Read back through manager
    creds = manager.get_credentials("https://reddit.com/login")
    assert creds == ("reddit_user", "reddit_password_456")


def test_encrypted_vault_wrong_password_raises(tmp_path: Path):
    """Verify DecryptionError is raised when unlocking vault with invalid password."""
    vault_file = tmp_path / "credentials.enc"
    manager = CredentialManager(vault_path=vault_file)

    manager.save_to_encrypted_vault(
        domain="example.com",
        username="usr",
        password="pwd",
        master_password="correct_password",
    )

    with pytest.raises(DecryptionError, match="Failed to decrypt vault"):
        manager.read_encrypted_vault("wrong_password")


def test_encrypted_vault_corrupted_data_raises(tmp_path: Path):
    """Verify DecryptionError is raised when ciphertext/tag is tampered with."""
    vault_file = tmp_path / "credentials.enc"
    manager = CredentialManager(vault_path=vault_file)

    manager.save_to_encrypted_vault(
        domain="example.com",
        username="usr",
        password="pwd",
        master_password="correct_password",
    )

    # Tamper with the tag
    data = json.loads(vault_file.read_text(encoding="utf-8"))
    tampered_tag = "0" * 32
    data["tag"] = tampered_tag
    vault_file.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DecryptionError):
        manager.read_encrypted_vault("correct_password")


def test_encrypted_vault_invalid_format_raises(tmp_path: Path):
    """Verify InvalidVaultFormat is raised for wrong version, non-hex, or invalid field lengths."""
    vault_file = tmp_path / "credentials.enc"
    manager = CredentialManager(vault_path=vault_file)

    # 1. Invalid version
    vault_file.write_text(json.dumps({"version": 2}), encoding="utf-8")
    with pytest.raises(InvalidVaultFormat, match="Unsupported vault version"):
        manager.read_encrypted_vault("any_password")

    # 2. Non-hex fields
    vault_file.write_text(
        json.dumps(
            {"version": 1, "salt": "zzz", "nonce": "zzz", "tag": "zzz", "ciphertext": "zzz"}
        ),
        encoding="utf-8",
    )
    with pytest.raises(InvalidVaultFormat, match="Vault record contains non-hex fields"):
        manager.read_encrypted_vault("any_password")

    # 3. Invalid field lengths (valid hex, but wrong byte counts)
    vault_file.write_text(
        json.dumps(
            {
                "version": 1,
                "salt": "00" * 8,  # 8B instead of 16B
                "nonce": "00" * 6,  # 6B instead of 12B
                "tag": "00" * 8,  # 8B instead of 16B
                "ciphertext": "00" * 10,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(InvalidVaultFormat, match="Invalid field lengths in vault"):
        manager.read_encrypted_vault("any_password")

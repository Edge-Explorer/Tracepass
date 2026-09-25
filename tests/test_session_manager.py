import json
import time
from pathlib import Path

from core.session_manager import SessionManager


def test_domain_normalization():
    """Verify that domain strings and complex URLs normalize to clean lowercase hostnames and distinct origins."""
    assert SessionManager.normalize_origin("reddit.com") == "https://reddit.com"
    assert SessionManager.normalize_origin("https://Discord.com/login") == "https://discord.com"
    assert (
        SessionManager.normalize_origin("http://Sub.Domain.org:8080/path?q=1")
        == "http://sub.domain.org:8080"
    )
    # Distinct origins produce distinct session file paths
    manager = SessionManager(storage_dir=Path("/tmp/sessions"))
    path_https = manager.get_session_path("https://example.com")
    path_http = manager.get_session_path("http://example.com:8080")
    assert path_https != path_http


def test_storage_only_session_acceptance(tmp_path: Path):
    """SPA apps with tokens in localStorage/sessionStorage (and 0 cookies) must be accepted."""
    manager = SessionManager(storage_dir=tmp_path)
    manager.save_session(
        "https://discord.com",
        cookies=[],  # 0 cookies
        local_storage={"token": "jwt_secret_token_123"},
    )
    assert manager.has_valid_session("https://discord.com") is True
    loaded = manager.load_session("https://discord.com")
    assert loaded is not None
    assert loaded["local_storage"]["token"] == "jwt_secret_token_123"


def test_session_path_uses_sha256_hash(tmp_path: Path):
    """Verify session path matches ~/.tracepass/sessions/<sha256_of_domain>.json."""
    manager = SessionManager(storage_dir=tmp_path)
    session_file = manager.get_session_path("https://example.com/login")

    assert session_file.parent == tmp_path
    assert (
        session_file.name == "100680ad546ce6a577f42f52df33b4cfdca756859e664b8d7de329b150d09ce9.json"
    )


def test_save_and_load_session(tmp_path: Path):
    """Verify atomic save, load, and presence validation."""
    manager = SessionManager(storage_dir=tmp_path)
    cookies = [{"name": "auth_token", "value": "xyz987", "domain": "example.com"}]
    storage = {"user_id": "12345"}

    assert manager.has_valid_session("example.com") is False

    saved_path = manager.save_session(
        "example.com",
        cookies=cookies,
        session_storage=storage,
        local_storage={"theme": "dark"},
    )
    assert saved_path.is_file()

    assert manager.has_valid_session("example.com") is True

    loaded = manager.load_session("example.com")
    assert loaded is not None
    assert loaded["domain"] == "https://example.com"
    assert loaded["cookies"] == cookies
    assert loaded["session_storage"] == storage
    assert loaded["local_storage"] == {"theme": "dark"}


def test_session_expiry(tmp_path: Path):
    """Sessions older than max_age_seconds must be rejected as invalid."""
    manager = SessionManager(storage_dir=tmp_path)
    cookies = [{"name": "sid", "value": "123"}]

    manager.save_session("example.com", cookies=cookies)

    # Directly manipulate creation timestamp to simulate old session
    session_file = manager.get_session_path("example.com")
    data = json.loads(session_file.read_text(encoding="utf-8"))
    data["created_at"] = time.time() - 1000  # 1000 seconds ago
    session_file.write_text(json.dumps(data), encoding="utf-8")

    # Valid within 2000s, but expired within 500s
    assert manager.has_valid_session("example.com", max_age_seconds=2000) is True
    assert manager.has_valid_session("example.com", max_age_seconds=500) is False


def test_session_invalidation(tmp_path: Path):
    """Invalidating a session deletes the file from disk."""
    manager = SessionManager(storage_dir=tmp_path)
    manager.save_session("example.com", cookies=[{"name": "token", "value": "abc"}])

    assert manager.has_valid_session("example.com") is True

    deleted = manager.invalidate_session("example.com")
    assert deleted is True
    assert manager.has_valid_session("example.com") is False
    assert manager.load_session("example.com") is None

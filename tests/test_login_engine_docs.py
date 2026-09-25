import json
import re
import textwrap
from pathlib import Path
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
DESIGN = ROOT / "docs" / "login-engine.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(document: str, heading: str) -> str:
    """Return the Markdown content below a heading, up to its next peer heading."""
    level = len(heading) - len(heading.lstrip("#"))
    pattern = rf"(?ms)^{re.escape(heading)}\s*$\n(.*?)(?=^#{{1,{level}}}\s|\Z)"
    match = re.search(pattern, document)
    assert match is not None, f"missing section: {heading}"
    return match.group(1)


def github_anchor(heading: str) -> str:
    """Approximate GitHub's anchor generation for the headings used in this repo."""
    anchor = heading.strip().lower()
    anchor = re.sub(r"[^\w\- ]", "", anchor, flags=re.UNICODE)
    return anchor.replace(" ", "-")


def headings(document: str) -> set[str]:
    return {
        github_anchor(match.group(1)) for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", document)
    }


def markdown_rows(document_section: str) -> list[list[str]]:
    rows = []
    for line in document_section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", line.strip("|"))]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


@pytest.mark.parametrize("document_path", [README, DESIGN], ids=lambda path: path.name)
def test_local_markdown_links_resolve(document_path: Path):
    """Every relative link in the changed docs points to a file and valid heading."""
    document = read(document_path)
    links = re.findall(r"(?<!!)\[[^]]+\]\(([^)]+)\)", document)

    for raw_target in links:
        target = unquote(raw_target.strip().split(maxsplit=1)[0].strip("<>"))
        if target.startswith(("http://", "https://", "mailto:")):
            continue

        relative_path, _, fragment = target.partition("#")
        linked_path = document_path if not relative_path else document_path.parent / relative_path
        linked_path = linked_path.resolve()
        assert linked_path.is_file(), f"{document_path.name}: missing link target {target}"
        if fragment:
            assert fragment in headings(read(linked_path)), (
                f"{document_path.name}: missing link fragment {target}"
            )


def test_login_flow_taxonomy_matches_v1_scope_across_documents():
    design = read(DESIGN)
    readme = read(README)
    taxonomy = section(design, "## 2. Login Flow Taxonomy")
    flow_headings = re.findall(r"(?m)^### Type (\d+): (.+)$", taxonomy)

    assert [number for number, _ in flow_headings] == [str(number) for number in range(1, 10)]
    assert "Types 1–9" in section(design, "## Document Purpose")
    assert "Type 7 registration" in section(design, "## Document Purpose")

    readme_flows = markdown_rows(section(readme, "### Planned Supported Login Flow Types (v1)"))
    assert len(readme_flows[1:]) == 6
    assert all("Registration" not in row[0] for row in readme_flows[1:])
    assert "First-time account registration and sign-up flows are not supported in v1" in section(
        readme, "### What is Out of Scope"
    )


def test_design_toc_and_architecture_cover_the_complete_pipeline():
    design = read(DESIGN)
    toc = section(design, "## Table of Contents")
    toc_entries = re.findall(r"(?m)^\d+\. \[[^]]+\]\(#(\d+)-", toc)
    assert toc_entries == [str(number) for number in range(1, 13)]

    architecture = section(design, "## 3. System Architecture")
    components = [
        "Session Cache Checker",
        "Credential Resolver",
        "Login Flow Analyzer",
        "Login Executor",
        "Authentication Verifier",
    ]
    assert all(component in architecture for component in components)


def test_credentials_are_kept_out_of_llm_logs_and_plaintext_storage():
    credentials = section(read(DESIGN), "## 4. Credential Management")
    security = section(credentials, "### 4.2 Credential Security Constraints")

    assert "**never** included in Gemini/LLM API prompts" in security
    assert "**never** written to logfiles" in security
    assert "**never** stored in plaintext on disk" in security
    assert "Python execution layer" in security
    assert "Playwright's `fill()` call" in security


def test_encrypted_credential_fallback_has_a_parseable_versioned_contract():
    decision = section(read(DESIGN), "### Decision 4: Credential Storage")
    record_match = re.search(r"```json\n(.*?)\n\s*```", decision, flags=re.DOTALL)
    assert record_match is not None
    record = json.loads(textwrap.dedent(record_match.group(1)))

    assert list(record) == ["version", "salt", "nonce", "tag", "ciphertext"]
    assert record["version"] == 1
    assert "PBKDF2-HMAC-SHA-256 with 600,000 iterations" in decision
    assert "16-byte (128-bit) salt" in decision
    assert "12-byte (96-bit) nonce" in decision
    assert "16-byte (128-bit) GCM authentication tag" in decision
    assert "verify the GCM tag before processing payload" in decision


def test_session_persistence_contract_uses_one_secure_global_location():
    design = read(DESIGN)
    readme = read(README)
    session_lifecycle = section(design, "## 5. Session Lifecycle")
    storage_decision = section(design, "### Decision 3: Session Storage Location")
    documented_files = set(re.findall(r"`(~/.tracepass/sessions/[^`]+\.json)`", design))

    assert documented_files == {"~/.tracepass/sessions/<sha256_of_domain>.json"}
    assert "scheme + host" in session_lifecycle
    assert "does not capture `sessionStorage` natively" in session_lifecycle
    assert "re-injecting those entries during context restoration" in session_lifecycle
    assert "`chmod 600`" in storage_decision
    assert "**Session persistence** (planned)" in readme


@pytest.mark.parametrize(
    ("hostname", "expected_key"),
    [
        ("example.com", "TRACEPASS_OTP_EXAMPLE_COM"),
        ("sub.site-app.org", "TRACEPASS_OTP_SUB_SITE_APP_ORG"),
    ],
)
def test_otp_environment_keys_use_shell_safe_domain_normalization(hostname, expected_key):
    normalized = re.sub(r"[^A-Za-z0-9]", "_", hostname).upper()
    assert f"TRACEPASS_OTP_{normalized}" == expected_key

    readme = read(README)
    design = read(DESIGN)
    assert expected_key in design
    if hostname == "example.com":
        assert expected_key in readme

    for document in (readme, design):
        assert "uppercase" in document.lower()
        assert "dots" in document.lower()
        assert "dashes" in document.lower()


def test_failure_mode_table_keeps_regex_pipes_inside_the_detection_cell():
    """Regression: raw regex pipes previously split Wrong Credentials into extra columns."""
    failure_modes = section(read(DESIGN), "## 8. Edge Cases and Failure Modes")
    rows = markdown_rows(failure_modes)

    assert rows[0] == ["Edge Case", "Detection", "Handling Strategy"]
    assert all(len(row) == 3 for row in rows)
    wrong_credentials = next(row for row in rows if "Wrong Credentials" in row[0])
    assert "incorrect&#124;invalid&#124;wrong&#124;failed" in wrong_credentials[1]
    assert "do not retry automatically" in wrong_credentials[2]


def test_retry_policy_preserves_safe_behavior_for_every_documented_failure():
    retry_policy = section(read(DESIGN), "### Decision 5: Login Failure Retry Policy")
    rows = markdown_rows(retry_policy)
    behavior = {row[0].strip("`"): row[1] for row in rows[1:]}

    assert behavior == {
        "CredentialRejected": "Never retry. Raise immediately.",
        "PageLoadTimeout": "Retry once after 3-second delay.",
        "MultiStepTransitionTimeout": "Retry once by reloading from scratch.",
        "CaptchaRequired": "Pause for solver or user. No auto-retry.",
        "TwoFactorTimeout": "Abort. Raise immediately.",
        "AccountLocked": "Abort immediately with cooldown info.",
        "LoginFormNotFound": "Abort immediately.",
        "NavigationLoopDetected": "Abort immediately.",
    }


def test_field_selector_map_and_checklist_agree_on_all_five_outputs():
    design = read(DESIGN)
    expected = {"username", "password", "submit", "next-button", "modal-trigger"}
    complexity = section(design, "### 10.2 Login Flow Analysis (DOM Scan)")
    checklist = section(design, "## 12. Implementation Checklist")

    complexity_fields = re.search(r"at most 5 key-value pairs: ([^)]+)", complexity)
    checklist_fields = re.search(r"all 5 field types \(([^)]+)\)", checklist)
    assert complexity_fields is not None
    assert checklist_fields is not None
    assert {item.strip() for item in complexity_fields.group(1).split(",")} == expected
    assert {item.strip() for item in checklist_fields.group(1).split(",")} == expected

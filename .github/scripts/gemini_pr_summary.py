import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

COMMENT_MARKER = "<!-- tracepass-gemini-pr-summary -->"
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_DIFF_CHARS = 50000


def get_git_diff(base_ref: str) -> str:
    """Extract git diff for the pull request."""
    # Attempt to read from environment variable first
    diff = os.environ.get("PR_DIFF", "").strip()
    if diff:
        return diff

    try:
        subprocess.run(
            ["git", "fetch", "origin", base_ref, "--depth=100"], check=False, capture_output=True
        )
        res = subprocess.run(
            ["git", "diff", f"origin/{base_ref}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        if res.stdout.strip():
            return res.stdout
    except Exception as e:
        print(f"Warning: git diff command failed: {e}")

    # Fallback to general git diff HEAD~1 if shallow clone
    try:
        res = subprocess.run(
            ["git", "diff", "HEAD~1...HEAD"], capture_output=True, text=True, check=True
        )
        return res.stdout
    except Exception:
        return ""


def get_changed_files_list(base_ref: str) -> list[str]:
    """Retrieve list of modified files."""
    try:
        res = subprocess.run(
            ["git", "diff", "--name-status", f"origin/{base_ref}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        if lines:
            return lines
    except Exception:
        pass

    try:
        res = subprocess.run(
            ["git", "diff", "--name-status", "HEAD~1...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def generate_gemini_summary(api_key: str, model_name: str, prompt: str) -> str:
    """Call Google Gemini API using urllib with high token limit."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
            candidates = result.get("candidates", [])
            if not candidates:
                raise ValueError("No candidates returned by Gemini API")
            text = candidates[0]["content"]["parts"][0]["text"]
            return text
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        if model_name != "gemini-2.0-flash" and (
            "not found" in error_body.lower() or e.code == 404
        ):
            print(f"Model {model_name} returned 404, falling back to gemini-2.0-flash...")
            return generate_gemini_summary(api_key, "gemini-2.0-flash", prompt)
        raise RuntimeError(f"Gemini API Error (HTTP {e.code}): {error_body}") from e


def post_or_update_pr_comment(
    github_token: str,
    repo: str,
    pr_number: str,
    comment_body: str,
) -> None:
    """Post comment or update existing summary comment on PR."""
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
        "User-Agent": "Tracepass-CI-Gemini-Bot",
    }

    full_comment = f"{COMMENT_MARKER}\n{comment_body}"

    list_url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    req = urllib.request.Request(list_url, headers=headers, method="GET")

    existing_comment_id = None
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            comments = json.loads(resp.read().decode("utf-8"))
            for c in comments:
                if COMMENT_MARKER in c.get("body", ""):
                    existing_comment_id = c["id"]
                    break
    except Exception as e:
        print(f"Note: Could not search existing comments ({e}), creating a new one.")

    payload = json.dumps({"body": full_comment}).encode("utf-8")

    if existing_comment_id:
        update_url = f"https://api.github.com/repos/{repo}/issues/comments/{existing_comment_id}"
        update_req = urllib.request.Request(
            update_url, data=payload, headers=headers, method="PATCH"
        )
        with urllib.request.urlopen(update_req, timeout=30) as resp:
            print(f"Successfully updated PR #{pr_number} summary comment.")
    else:
        create_req = urllib.request.Request(list_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(create_req, timeout=30) as resp:
            print(f"Successfully posted new PR #{pr_number} summary comment.")


def main():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("::warning::GEMINI_API_KEY secret is not set. Skipping Gemini PR summary.")
        sys.exit(0)

    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    pr_number = os.environ.get("PR_NUMBER", "").strip()
    pr_title = os.environ.get("PR_TITLE", "No Title")
    pr_body = os.environ.get("PR_BODY", "No description provided.")
    base_ref = os.environ.get("GITHUB_BASE_REF", "main").strip() or "main"
    model_name = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip()

    if not repo or not pr_number or not github_token:
        print("Missing required GitHub environment variables.")
        sys.exit(1)

    diff = get_git_diff(base_ref)
    file_list = get_changed_files_list(base_ref)

    truncated_note = ""
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n...[Diff truncated due to size limits]..."
        truncated_note = "\n*(Note: Large diff was truncated to fit context limits)*"

    files_summary_text = "\n".join(file_list) if file_list else "All files in PR diff"

    prompt = f"""You are an elite principal software architect and code reviewer.
Analyze the following Pull Request details, modified file list, and Git Diff for the repository '{repo}'.

Your goal is to provide a DEEP, THOROUGH, and COMPREHENSIVE Pull Request review and file-by-file breakdown so that the reviewers understand every single nuance and change without having to open and read every file manually.

### Pull Request Metadata:
- **Title**: {pr_title}
- **PR #**: {pr_number}
- **Target Branch**: {base_ref}
- **User Description**:
{pr_body}

### Changed Files:
{files_summary_text}

### Git Diff:
```diff
{diff}
```

---

### Format your response strictly following this structure:

# 🤖 PR Detailed Review & Summary by Gemini Code Intelligence

## 1. Executive Summary (In Plain English)
[Provide a clear, rich paragraph explaining the purpose, scope, and high-level architectural impact of this Pull Request.]

## 2. Motivation & Root Cause Analysis
[Explain what was missing, broken, or why this implementation was necessary. Break down specific shortcomings or objectives in numbered bullet points.]

## 3. Step-by-Step Technical Solution
[Detail the exact technical steps, tools, algorithms, and architectural mechanisms introduced or modified in this PR. Use numbered points with backticks for file names, symbols, and functions.]

## 4. File-by-File Breakdown & Key Implementation Details
[Provide a detailed markdown table covering EVERY single file touched in the diff. In the "Purpose & Key Implementation Details" column, write 2-4 comprehensive sentences explaining the exact classes, functions, configurations, or logic changes made in that file.]

| File | Action | Purpose & Key Implementation Details |
| :--- | :--- | :--- |
| `path/to/file` | `Added` / `Modified` / `Deleted` | **[Key component/function]**: [Deep explanation of the implementation details, parameters added, logic handled, or configs introduced] |

## 5. Architecture, Reliability & Security Considerations
- **Architecture & Maintainability**: [Analysis of design patterns, modularity, and integration]
- **Security & Secrets**: [Validation of secret safety, inputs, and error handling]
- **Performance**: [Runtime overhead, efficiency, or caching considerations]

## 6. Risk Assessment & Edge Cases
- **Overall Risk Level**: [🟢 Low / 🟡 Medium / 🔴 High]
- **Potential Edge Cases / Side Effects**: [List any potential breaking changes or scenarios to watch out for]

## 7. Reviewer & Testing Verification Checklist
- [ ] [Specific verification action item for the reviewer]
- [ ] [Specific test or validation scenario]
"""

    print(f"Generating comprehensive review using model '{model_name}'...")
    try:
        summary_md = generate_gemini_summary(api_key, model_name, prompt)
        if truncated_note:
            summary_md += truncated_note

        post_or_update_pr_comment(github_token, repo, pr_number, summary_md)
    except Exception as e:
        print(f"::error::Failed to generate or post Gemini PR summary: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

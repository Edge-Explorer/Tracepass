import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

COMMENT_MARKER = "<!-- tracepass-gemini-pr-summary -->"
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_DIFF_CHARS = 35000  # Safeguard against huge diffs


def get_git_diff() -> str:
    """Extract git diff for the pull request."""
    # Attempt to read from environment variable first
    diff = os.environ.get("PR_DIFF", "")
    if diff:
        return diff

    # Otherwise extract via git command comparing against origin/main or base ref
    base_ref = os.environ.get("GITHUB_BASE_REF", "main")
    try:
        subprocess.run(["git", "fetch", "origin", base_ref], check=False, capture_output=True)
        res = subprocess.run(
            ["git", "diff", f"origin/{base_ref}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout
    except Exception as e:
        print(f"Warning: Failed to get diff via git command: {e}")
        return ""


def get_changed_files_list() -> list[str]:
    """Retrieve list of modified files."""
    base_ref = os.environ.get("GITHUB_BASE_REF", "main")
    try:
        res = subprocess.run(
            ["git", "diff", "--name-status", f"origin/{base_ref}...HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    except Exception:
        return []


def generate_gemini_summary(api_key: str, model_name: str, prompt: str) -> str:
    """Call Google Gemini API using urllib."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
            candidates = result.get("candidates", [])
            if not candidates:
                raise ValueError("No candidates returned by Gemini API")
            text = candidates[0]["content"]["parts"][0]["text"]
            return text
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        # Try fallback model if 2.5-flash is unavailable
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

    # Format body with marker
    full_comment = f"{COMMENT_MARKER}\n{comment_body}"

    # Check if a comment with this marker already exists
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
    model_name = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip()

    if not repo or not pr_number or not github_token:
        print(
            "Missing required GitHub environment variables (GITHUB_REPOSITORY, PR_NUMBER, GITHUB_TOKEN)."
        )
        sys.exit(1)

    diff = get_git_diff()
    file_list = get_changed_files_list()

    truncated_note = ""
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n...[Diff truncated due to size limits]..."
        truncated_note = "\n*(Note: Diff was truncated due to character limits)*"

    files_summary_text = "\n".join(file_list) if file_list else "Not available via git status"

    prompt = f"""You are an expert senior code reviewer and software architect.
Analyze the following Pull Request details and Git Diff for the repository '{repo}'.

Generate a structured, clean, and comprehensive Pull Request Summary in Markdown.

### PR Information:
- **Title**: {pr_title}
- **PR #**: {pr_number}
- **Description**:
{pr_body}

### Changed Files:
{files_summary_text}

### Git Diff:
```diff
{diff}
```

### Please output your review strictly in this markdown format:
## 🤖 Gemini 2.5 Flash Pull Request Summary

### ⚡ Executive Summary
[A concise 2-3 sentence overview explaining what this PR accomplishes, why it was made, and the core outcome]

### 📂 File-by-File Changes & Impact
| File | Action | Summary of Changes |
| :--- | :--- | :--- |
| `path/to/file` | `Added` / `Modified` / `Deleted` | [One-sentence clear summary of what changed inside this file] |

### 🔍 Key Architectural & Logic Highlights
- [Bullet points of significant algorithmic, structural, or configuration changes]

### ⚠️ Risk & Breaking Change Assessment
- **Risk Level**: [🟢 Low / 🟡 Medium / 🔴 High]
- **Details**: [Any potential side-effects, backward compatibility concerns, or missing edge case handling]

### 🧪 Reviewer & Verification Checklist
- [ ] [Verification point 1]
- [ ] [Verification point 2]
"""

    print(f"Generating summary using model '{model_name}'...")
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

"""
Version information for the Collections API.

Version info is injected at build time via environment variables.
For local development, it reads from git directly.
"""

import os
import subprocess
from datetime import datetime
from functools import lru_cache


@lru_cache(maxsize=1)
def get_version_info() -> dict:
    """
    Get version information for the running application.

    Returns version info from:
    1. Build-time environment variables (in Docker/Lambda)
    2. Live git commands (local development)
    """
    # Check for build-time injected values first
    git_sha = os.getenv("GIT_SHA")
    git_branch = os.getenv("GIT_BRANCH")
    build_timestamp = os.getenv("BUILD_TIMESTAMP")
    app_version = os.getenv("APP_VERSION", "0.1.0")

    # If not set (local dev), try to get from git
    if not git_sha:
        git_sha = _run_git_command("git rev-parse --short HEAD")
    if not git_branch:
        git_branch = _run_git_command("git rev-parse --abbrev-ref HEAD")
    if not build_timestamp:
        build_timestamp = datetime.utcnow().isoformat() + "Z"

    return {
        "version": app_version,
        "git_sha": git_sha or "unknown",
        "git_branch": git_branch or "unknown",
        "build_timestamp": build_timestamp,
        "environment": _detect_environment(),
    }


def _run_git_command(command: str) -> str | None:
    """Run a git command and return output, or None on failure."""
    try:
        result = subprocess.run(
            command.split(),
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.path.dirname(__file__) or "."
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _detect_environment() -> str:
    """Detect the runtime environment."""
    if os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return "lambda"
    if os.getenv("AWS_EXECUTION_ENV"):
        return "aws"
    if os.getenv("CODESPACE_NAME"):
        return "codespace"
    return "local"

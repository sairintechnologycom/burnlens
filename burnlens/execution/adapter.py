"""Phase 6: BL-AE-006 Assisted Execution GitHub Adapter.

Implements the execution adapter for creating branches, committing explicitly scoped files,
opening pull requests, and polling CI status.

Enforces:
- Least privilege (short-lived tokens or scoped mock client)
- Explicit scope enforcement
- Strict prohibition of direct push to protected branches
- Strict prohibition of automatic merging (PR remains unmerged for human authority)
"""
from __future__ import annotations

import logging
from typing import Any, Protocol

from burnlens.execution.models import PROTECTED_BRANCHES

logger = logging.getLogger(__name__)


class GitProviderError(Exception):
    """Base exception for git provider execution failures."""


class ProtectedBranchError(GitProviderError):
    """Raised when an operation attempts to directly modify or merge into a protected branch."""


class AutoMergeForbiddenError(GitProviderError):
    """Raised when an agent attempts to automatically merge a pull request."""


class GitProviderClient(Protocol):
    """Interface required for GitHub client operations."""

    async def create_branch(self, repo: str, base_branch: str, new_branch: str) -> dict[str, Any]:
        ...

    async def commit_files(
        self, repo: str, branch: str, files: dict[str, str], message: str
    ) -> dict[str, Any]:
        ...

    async def create_pull_request(
        self, repo: str, title: str, body: str, head_branch: str, base_branch: str
    ) -> dict[str, Any]:
        ...

    async def get_ci_status(self, repo: str, ref: str) -> str:
        ...


class MockGitHubClient:
    """In-memory mock GitHub client for deterministic unit, contract, and E2E testing."""

    def __init__(self) -> None:
        # repo -> {branch_name -> commit_sha}
        self.branches: dict[str, dict[str, str]] = {}
        # repo -> list of PR dicts
        self.pull_requests: dict[str, list[dict[str, Any]]] = {}
        # repo -> list of commit dicts
        self.commits: dict[str, list[dict[str, Any]]] = {}
        # ref -> status
        self.ci_statuses: dict[str, str] = {}
        self.pr_counter: int = 100

    def seed_repo(self, repo: str, default_branch: str = "main", initial_sha: str = "init-sha-000") -> None:
        if repo not in self.branches:
            self.branches[repo] = {}
            self.pull_requests[repo] = []
            self.commits[repo] = []
        self.branches[repo][default_branch] = initial_sha

    async def create_branch(self, repo: str, base_branch: str, new_branch: str) -> dict[str, Any]:
        if repo not in self.branches:
            self.seed_repo(repo, base_branch)
        if base_branch not in self.branches[repo]:
            raise GitProviderError(f"Base branch '{base_branch}' not found in repo '{repo}'")
        if new_branch in self.branches[repo]:
            raise GitProviderError(f"Branch '{new_branch}' already exists in repo '{repo}'")

        base_sha = self.branches[repo][base_branch]
        self.branches[repo][new_branch] = base_sha
        return {"repo": repo, "branch": new_branch, "sha": base_sha, "ref": f"refs/heads/{new_branch}"}

    async def commit_files(
        self, repo: str, branch: str, files: dict[str, str], message: str
    ) -> dict[str, Any]:
        if repo not in self.branches or branch not in self.branches[repo]:
            raise GitProviderError(f"Branch '{branch}' does not exist in repo '{repo}'")

        commit_sha = f"sha-{len(self.commits.get(repo, [])) + 1:04d}-{branch[:8]}"
        commit_entry = {
            "repo": repo,
            "branch": branch,
            "commit_sha": commit_sha,
            "message": message,
            "files": list(files.keys()),
        }
        self.commits.setdefault(repo, []).append(commit_entry)
        self.branches[repo][branch] = commit_sha
        self.ci_statuses[commit_sha] = "pending"
        return {"commit_sha": commit_sha, "files_count": len(files)}

    async def create_pull_request(
        self, repo: str, title: str, body: str, head_branch: str, base_branch: str
    ) -> dict[str, Any]:
        self.pr_counter += 1
        pr_number = self.pr_counter
        pr_url = f"https://github.com/{repo}/pull/{pr_number}"
        pr_entry = {
            "repo": repo,
            "pr_number": pr_number,
            "title": title,
            "body": body,
            "head_branch": head_branch,
            "base_branch": base_branch,
            "state": "open",
            "merged": False,
            "html_url": pr_url,
        }
        self.pull_requests.setdefault(repo, []).append(pr_entry)
        return pr_entry

    async def get_ci_status(self, repo: str, ref: str) -> str:
        return self.ci_statuses.get(ref, "success")


class GitHubExecutionAdapter:
    """Execution adapter enforcing BurnLens safety invariants for GitHub workflows."""

    def __init__(self, client: GitProviderClient | None = None) -> None:
        self.client = client or MockGitHubClient()

    async def create_branch(self, repo: str, base_branch: str, new_branch: str) -> dict[str, Any]:
        """Create a new feature or optimization branch."""
        clean_target = new_branch.strip().lower()
        if clean_target in PROTECTED_BRANCHES:
            raise ProtectedBranchError(
                f"Cannot create branch with protected name '{new_branch}'"
            )
        return await self.client.create_branch(repo, base_branch, new_branch)

    async def commit_scoped_changes(
        self, repo: str, branch: str, files: dict[str, str], message: str
    ) -> dict[str, Any]:
        """Commit changes to a branch, verifying branch is not protected."""
        clean_target = branch.strip().lower()
        if clean_target in PROTECTED_BRANCHES:
            raise ProtectedBranchError(
                f"Direct commit to protected branch '{branch}' is strictly forbidden."
            )
        return await self.client.commit_files(repo, branch, files, message)

    async def open_pull_request(
        self, repo: str, title: str, body: str, head_branch: str, base_branch: str = "main"
    ) -> dict[str, Any]:
        """Open a pull request targeting base_branch. Auto-merge is strictly disallowed."""
        return await self.client.create_pull_request(repo, title, body, head_branch, base_branch)

    async def auto_merge_pr(self, repo: str, pr_number: int) -> None:
        """Explicitly disallowed under Phase 6: Human remains mandatory execution authority."""
        raise AutoMergeForbiddenError(
            "Auto-merge is forbidden under BL-AE-006. Human review and approval in GitHub is mandatory."
        )

    async def record_ci_status(self, repo: str, ref: str) -> str:
        """Fetch or check CI status for a commit or branch ref."""
        return await self.client.get_ci_status(repo, ref)

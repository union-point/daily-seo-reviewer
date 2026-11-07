"""Integration-gate Issue delivery, retryable from a saved preflight artifact."""

import argparse
import os
import re
from pathlib import Path
from typing import Iterator

import requests

from seo_reviewer.models import Preflight

ISSUE_TITLE = "Daily SEO reviews"


class GitHubDelivery:
    def __init__(self, repository: str, token: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Expected owner/repository")
        self.base = f"https://api.github.com/repos/{repository}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "DailySEOReviewer/0.1",
        })

    def request(self, method: str, path: str, **kwargs: object) -> object:
        response = self.session.request(
            method, self.base + path, timeout=(5, 20), allow_redirects=False, **kwargs
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"GitHub delivery returned HTTP {response.status_code}")
        return response.json()

    def items(self, path: str, **params: object) -> Iterator[dict]:
        for page in range(1, 1001):
            items = self.request("GET", path, params={**params, "per_page": 100, "page": page})
            if not isinstance(items, list):
                raise ValueError("Expected a GitHub list response")
            yield from items
            if len(items) < 100:
                return
        raise RuntimeError("GitHub pagination limit reached; refusing an incomplete deduplication check")

    def deliver(self, run_id: str, body: str) -> bool:
        """Return False if this run was already delivered. Workflow serialization prevents races."""
        issue = next((
            item for item in self.items("/issues", state="all", sort="created", direction="asc")
            if item.get("title") == ISSUE_TITLE and "pull_request" not in item
        ), None)
        if issue is None:
            issue = self.request("POST", "/issues", json={
                "title": ISSUE_TITLE,
                "body": "Daily SEO Reviewer delivery thread. Subscribe to this Issue for notifications. Initial entries verify integrations; SEO reviews follow after the integration gate.",
            })
        path = f"/issues/{int(issue['number'])}/comments"
        marker = f"<!-- daily-seo-reviewer:{run_id} -->"
        content = marker + "\n" + body
        for comment in self.items(path):
            if marker in (comment.get("body") or ""):
                if comment["body"] == content:
                    return False
                # A retried deployment can turn a previously failed gate into a pass.
                self.request("PATCH", f"/issues/comments/{int(comment['id'])}", json={"body": content})
                return True
        self.request("POST", path, json={"body": content})
        return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deliver a saved integration preflight to the daily Issue")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--pages-url", default="")
    parser.add_argument("--deployment-result", choices=["success", "failure", "cancelled", "skipped"], required=True)
    args = parser.parse_args(argv)
    result = Preflight.model_validate_json(args.evidence.read_text(encoding="utf-8"))
    passed = result.passed and args.deployment_result == "success"
    body = (
        f"Integration preflight: **{'passed' if passed else 'incomplete / failed'}**\n\n"
        "This checks connectivity and permissions; it is not an SEO health review.\n\n"
        + "\n".join(f"- {check.name}: {check.status}" for check in result.checks)
        + f"\n- Pages deployment: {args.deployment_result}\n"
    )
    if args.deployment_result == "success" and args.pages_url:
        body += f"\n[Preflight evidence]({args.pages_url.rstrip('/')}/preflight.json)\n"
    if result.workflow_url:
        body += f"\n[Workflow run]({result.workflow_url})\n"
    try:
        delivery = GitHubDelivery(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
        try:
            sent = delivery.deliver(result.run_id, body)
        finally:
            delivery.session.close()
    except (KeyError, ValueError, RuntimeError, requests.RequestException) as exc:
        print(f"Issue delivery failed ({type(exc).__name__}); retry this job using the saved artifact")
        return 1
    print("Issue comment delivered" if sent else "Run already delivered; no duplicate comment")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

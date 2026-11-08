"""Retryable daily Issue delivery from a saved review artifact; never recrawl."""

import argparse
import os
import re
from pathlib import Path

import requests

from seo_reviewer.notification import GitHubDelivery
from seo_reviewer.render import safe_url
from seo_reviewer.review_models import Review


def review_comment(review: Review, pages_url: str, workflow_url: str, deployment: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', review.run_id):
        raise ValueError('Invalid review run ID')
    if not safe_url(workflow_url) or (deployment == 'success' and not safe_url(pages_url)):
        raise ValueError('Invalid delivery URL')
    coverage = review.coverage
    active = [finding for finding in review.findings if finding.state not in {'resolved', 'unverified'}]
    verification = sum(finding.state == 'unverified' for finding in review.findings)
    status = review.alert_status if review.alert_status in {'healthy', 'warning', 'critical', 'verification_required'} else 'verification_required'
    lines = [
        f'Daily SEO review: **{status}**', '',
        f"Coverage: {coverage['successful']}/{coverage['attempted']} attempted pages collected; {coverage['failed']} failed; {coverage['deferred']} deferred.",
        f'Active verified findings: {len(active)}; verification items: {verification}.',
        'Baseline only; no historical regression claims.' if review.baseline_only else 'Compared with stored successful observations.',
        'AI summary unavailable; deterministic review provided.' if review.narrative_source == 'deterministic' else 'AI explanation available; factual status and evidence are determined by code.',
        '', 'Top actions:',
    ]
    active_ids = {finding.id for finding in active}
    actions = [item.recommended_action for item in review.narrative.prioritized_issues if item.finding_id in active_ids][:3]
    lines += ['- ' + action for action in actions] or ['- No saved priority recommendations. See the report for recorded findings.']
    if verification:
        lines.append('- Recheck unverified findings before treating them as confirmed or resolved.')
    if deployment == 'success':
        lines += ['', f'[Review report]({pages_url.rstrip("/")}/reviews/{review.run_id}.html)']
    else:
        lines += ['', f'Publication unavailable (deployment: {deployment}). The saved review remains in workflow artifacts; retry deployment/delivery.']
    lines += ['', f'[Workflow run]({workflow_url})']
    return '\n'.join(lines)


def latest_delivery_review(directory: Path) -> Path | None:
    # v8 can flatten a single matching artifact; multiple attempts keep named folders.
    candidates = list(directory.glob('daily-delivery-*/review.json'))
    if candidates:
        return max(candidates, key=lambda path: int(path.parent.name.rsplit('-', 1)[1]))
    direct = directory / 'review.json'
    return direct if direct.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Deliver a saved daily review or pipeline failure')
    parser.add_argument('--artifact-dir', type=Path, required=True)
    parser.add_argument('--pages-url', default='')
    parser.add_argument('--workflow-url', required=True)
    parser.add_argument('--workflow-run-id', required=True)
    parser.add_argument('--deployment-result', choices=['success', 'failure', 'cancelled', 'skipped'], required=True)
    args = parser.parse_args(argv)
    delivery = None
    try:
        if not re.fullmatch(r'\d+', args.workflow_run_id) or not safe_url(args.workflow_url):
            raise ValueError('Invalid workflow identity')
        path = latest_delivery_review(args.artifact_dir)
        if path:
            review = Review.model_validate_json(path.read_text())
            marker = review.run_id
            body = review_comment(review, args.pages_url, args.workflow_url, args.deployment_result)
            passed = args.deployment_result == 'success' and review.collection_status == 'collected'
        else:
            marker = 'workflow-' + args.workflow_run_id
            body = f'Daily SEO review pipeline failed before a current review artifact was available. No current review is being claimed. Inspect the [workflow run]({args.workflow_url}) and retry the failed job.'
            passed = False
        delivery = GitHubDelivery(os.environ['GITHUB_REPOSITORY'], os.environ['GH_TOKEN'])
        sent = delivery.deliver(marker, body)
        print('Daily review comment delivered' if sent else 'Daily review already delivered; no duplicate comment')
        return 0 if passed else 1
    except (OSError, ValueError, KeyError, RuntimeError, requests.RequestException) as exc:
        print(f'Daily delivery failed ({type(exc).__name__}); retry from saved artifacts')
        return 1
    finally:
        if delivery is not None:
            delivery.session.close()


if __name__ == '__main__':
    raise SystemExit(main())

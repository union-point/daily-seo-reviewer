"""Bounded cohort collection and persistent successful comparison state."""

import calendar
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urldefrag, urlsplit

from lxml import etree

from seo_reviewer.collection import Collector
from seo_reviewer.config import Config, origin
from seo_reviewer.observations import Observation, observe
from seo_reviewer.preflight import sitemap_locations
from seo_reviewer.storage import RunStore
from seo_reviewer.state import ComparisonState


def article_date(url: str) -> tuple[int, int, int] | None:
    match = re.fullmatch(r'/weblog/(\d{4})/([a-z]{3})/(\d{1,2})/[^/]+/', urlsplit(url).path)
    if not match or urlsplit(url).query:
        return None
    year, month, day = match.groups()
    try:
        date = datetime(int(year), list(calendar.month_abbr).index(month.title()), int(day))
        return date.year, date.month, date.day
    except ValueError:
        return None


def select_cohort(site: str, urls: list[str]) -> list[str]:
    articles = sorted({url for url in urls if article_date(url)}, key=lambda url: (article_date(url), url), reverse=True)
    if len(articles) < 48:
        raise ValueError('Need at least 48 dated articles to establish the fixed cohort')
    return [site + '/', site + '/weblog/', *articles[:48]]


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(value, output, indent=2, ensure_ascii=False)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def discover(collector: Collector) -> tuple[list[str], bool, list[str]]:
    pending = [collector.config.site_url + '/sitemap.xml']
    seen: set[str] = set()
    urls: set[str] = set()
    errors = []
    while pending and len(seen) < collector.config.max_sitemaps:
        url = pending.pop(0)
        if url in seen:
            continue
        seen.add(url)
        result = collector.fetch(url)
        try:
            if not result.ok:
                raise ValueError(result.evidence.error or f'HTTP {result.evidence.status_code}')
            kind, locations = sitemap_locations(result.body)
            scoped = {urldefrag(location)[0] for location in locations if collector.in_scope(location)}
            if kind == 'sitemapindex':
                pending.extend(sorted(scoped - seen))
            else:
                urls.update(scoped)
        except (ValueError, etree.LxmlError) as exc:
            errors.append(f'{url}: {exc}')
        if result.evidence.error == 'challenge_response':
            break
    deferred = sorted(set(pending) - seen)
    errors.extend(f'Deferred sitemap: {url}' for url in deferred)
    return sorted(urls), not errors, errors


def run_crawl(config: Config) -> dict:
    """Serialize state updates, finalize evidence first, then atomically publish state."""
    import fcntl
    config.data_dir.mkdir(parents=True, exist_ok=True)
    with (config.data_dir / '.crawl.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state_path = config.data_dir / 'state.json'
        state = (
            ComparisonState.model_validate_json(state_path.read_text())
            if state_path.exists() else ComparisonState(site_url=config.site_url)
        ).model_dump(mode='json')
        if state.get('schema_version') != 1 or state['site_url'] != config.site_url:
            raise ValueError('State schema/origin mismatch; use a separate data directory')
        if state['cohort'] and (len(state['cohort']) != 50 or len(set(state['cohort'])) != 50):
            raise ValueError('Invalid persisted cohort')
        if state['cohort'] and (
            state['cohort'][:2] != [config.site_url + '/', config.site_url + '/weblog/']
            or any(origin(url) != config.site_url for url in state['cohort'])
        ):
            raise ValueError('Persisted cohort does not match the configured origin')
        store = RunStore(config.data_dir)
        collector = Collector(config, store)
        started = datetime.now(UTC).isoformat()
        errors: list[str] = []
        observations: list[Observation] = []
        sitemap_urls: list[str] = []
        complete = False
        cohort = state['cohort']
        deferred: list[str] = []
        pending_new = set(state.get('pending_urls', []))
        try:
            collector.load_robots()
            if collector.robots is None:
                errors.append('Robots policy unavailable; no page requests made')
            else:
                sitemap_urls, complete, errors = discover(collector)
                if not cohort:
                    if complete:
                        try:
                            cohort = select_cohort(config.site_url, sitemap_urls)
                        except ValueError as exc:
                            errors.append(str(exc))
                    else:
                        errors.append('Complete sitemap discovery required to establish cohort')
                # Failed new URLs remain eligible until a successful observation exists.
                if state['cohort']:
                    pending_new.update(set(sitemap_urls) - set(state['known_sitemap_urls'] or state['sitemap_urls']))
                pending_new.difference_update(cohort)
                if complete:
                    pending_new.intersection_update(sitemap_urls)
                extras = sorted(pending_new)
                budget = config.max_pages - len(cohort)
                selected = list(cohort) + extras[:budget]
                deferred = extras[budget:]
                blocked = any(fetch.error == 'challenge_response' for fetch in collector.fetches)
                for url in selected:
                    if blocked:
                        deferred.append(url)
                        continue
                    result = collector.fetch(url)
                    observations.append(observe(result, store.run_id))
                    blocked = result.evidence.error == 'challenge_response'
        finally:
            collector.close()
        successful = [item for item in observations if item.outcome == 'success']
        previous = state['latest_successful']
        comparable = {item.evidence.requested_url: previous[item.evidence.requested_url] for item in observations if item.evidence.requested_url in previous}
        summary = {
            'schema_version': 1, 'kind': 'collection', 'run_id': store.run_id,
            'started_at': started, 'completed_at': datetime.now(UTC).isoformat(),
            'config': config.model_dump(mode='json'), 'cohort': cohort,
            'execution_context': 'github-actions' if os.environ.get('GITHUB_ACTIONS') == 'true' else 'local',
            'fetches': [fetch.model_dump(mode='json') for fetch in collector.fetches],
            'baseline_only': not state['latest_successful'], 'previous_observations': comparable,
            'observations': [item.model_dump(mode='json') for item in observations],
            'sitemap_urls': sitemap_urls, 'sitemap_complete': complete,
            'sitemap_added': sorted(set(sitemap_urls) - set(state['sitemap_urls'])) if state.get('sitemap_run_id') and complete else [],
            'sitemap_removed': sorted(set(state['sitemap_urls']) - set(sitemap_urls)) if state.get('sitemap_run_id') and complete else [],
            'deferred_urls': deferred, 'errors': errors,
            'comparable_pages': sum(item.evidence.requested_url in previous for item in successful),
            'request_errors': [fetch.model_dump(mode='json') for fetch in collector.fetches if fetch.error or (
                fetch.status_code is not None and fetch.status_code >= 400
                and not (fetch.requested_url == config.site_url + '/robots.txt' and fetch.status_code in {404, 410})
            )],
            'coverage': {'attempted': len(observations), 'successful': len(successful), 'failed': len(observations) - len(successful), 'deferred': len(deferred)},
        }
        summary['status'] = 'collection_failed' if not successful else ('partial_crawl' if errors or len(successful) != len(observations) or deferred else 'collected')
        with (store.path / 'collection.json').open('x', encoding='utf-8') as output:
            json.dump(summary, output, indent=2, ensure_ascii=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        state['cohort'] = cohort
        for item in successful:
            state['latest_successful'][item.evidence.requested_url] = item.model_dump(mode='json')
        pending_new.difference_update(item.evidence.requested_url for item in successful)
        state['pending_urls'] = sorted(pending_new)
        if complete:
            state['sitemap_urls'] = sitemap_urls
            state['sitemap_run_id'] = store.run_id
        state['known_sitemap_urls'] = sitemap_urls if complete else sorted(set(state['known_sitemap_urls']) | set(sitemap_urls))
        state['latest_run_id'] = store.run_id
        state['history'] = (state['history'] + [{'run_id': store.run_id, 'status': summary['status'], 'coverage': summary['coverage'], 'completed_at': summary['completed_at']}])[-90:]
        atomic_json(state_path, state)
        return summary

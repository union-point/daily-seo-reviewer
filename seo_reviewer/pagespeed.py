"""Optional, bounded PSI v5 collection; lab and returned field data stay separate."""

import json
import math
import os
import re
import time
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, Field

from seo_reviewer.collection import RETRYABLE, retry_delay
from seo_reviewer.config import Config, origin
from seo_reviewer.observations import Observation
from seo_reviewer.storage import RunStore

ENDPOINT = 'https://pagespeedonline.googleapis.com/pagespeedonline/v5/runPagespeed'
METRICS = {
    'lcp_ms': ('largest-contentful-paint', 'millisecond'),
    'cls': ('cumulative-layout-shift', 'unitless'),
    'fcp_ms': ('first-contentful-paint', 'millisecond'),
    'tbt_ms': ('total-blocking-time', 'millisecond'),
    'speed_index_ms': ('speed-index', 'millisecond'),
}
MAX_RESPONSE_BYTES = 8_000_000


class LighthouseAudit(BaseModel):
    id: str
    category: Literal['performance', 'seo']
    title: str
    description: str
    score: float | None = Field(default=None, ge=0, le=1)
    display_value: str | None = None
    numeric_value: float | None = None
    numeric_unit: str | None = None
    failed: bool = False


class FieldExperience(BaseModel):
    status: Literal['available', 'unavailable'] = 'unavailable'
    scope: Literal['page', 'origin'] = 'page'
    id: str | None = None
    overall_category: str | None = None
    # PSI's original percentile units/distributions are retained, never merged with lab.
    metrics: dict[str, dict] = Field(default_factory=dict)


class PageSpeedObservation(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    url: str
    strategy: Literal['mobile', 'desktop']
    collected_at: datetime
    status: Literal['success', 'incomplete', 'unavailable'] = 'unavailable'
    error: str | None = None
    attempts: int = 0
    http_status: int | None = None
    performance_score: float | None = Field(default=None, ge=0, le=100)
    seo_score: float | None = Field(default=None, ge=0, le=100)
    metrics: dict[str, float | None] = Field(default_factory=dict)
    audits: dict[str, LighthouseAudit] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    lighthouse_version: str | None = None
    final_url: str | None = None
    fetch_time: str | None = None
    crux_page: FieldExperience = Field(default_factory=FieldExperience)
    crux_origin: FieldExperience = Field(default_factory=lambda: FieldExperience(scope='origin'))
    body_path: str | None = None
    body_sha256: str | None = None


def measurement_key(item: PageSpeedObservation) -> str:
    return item.strategy + '\n' + item.url


def select_pages(observations: list[Observation], config: Config) -> list[str]:
    """Homepage, then shallow distinct path families; no discovery or domain rules."""
    urls = set()
    for item in observations:
        if item.outcome != 'success':
            continue
        try:
            if origin(item.evidence.requested_url) == origin(item.evidence.final_url) == config.site_url:
                urls.add(item.evidence.final_url)
        except ValueError:
            continue
    def parts(url: str) -> list[str]:
        return [part for part in urlsplit(url).path.split('/') if part]
    selected, depths, families, shapes = [], set(), set(), set()
    def shape(url: str) -> tuple[str, int, str]:
        path = parts(url)
        return (path[0] if path else '', len(path), path[-1].rsplit('.', 1)[-1] if path and '.' in path[-1] else '')
    while urls and len(selected) < config.pagespeed.max_pages:
        # Favor an index and a deeper detail page over several sibling indexes.
        url = min(urls, key=lambda url: (
            len(parts(url)) in depths, shape(url) in shapes,
            shape(url)[0] in families, len(parts(url)), bool(urlsplit(url).query), url,
        ))
        selected.append(url)
        depths.add(len(parts(url)))
        families.add(shape(url)[0])
        shapes.add(shape(url))
        urls.remove(url)
    return selected


def number(value: object, *, maximum: float | None = None) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        result = float(value)
    except OverflowError:
        return None
    if not math.isfinite(result) or result < 0:
        return None
    return result if maximum is None or result <= maximum else None


def mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def text_value(value: object, limit: int = 2000) -> str | None:
    return value[:limit].encode('utf-8', errors='replace').decode('utf-8') if isinstance(value, str) else None


def field_experience(value: object, scope: Literal['page', 'origin']) -> FieldExperience:
    value = mapping(value)
    metrics = {}
    for key, raw in list(mapping(value.get('metrics')).items())[:20]:
        raw = mapping(raw)
        percentile = number(raw.get('percentile'))
        if percentile is not None:
            distributions = []
            for row in raw.get('distributions', [])[:10] if isinstance(raw.get('distributions'), list) else []:
                row = mapping(row)
                distributions.append({k: v for k in ('min', 'max', 'proportion') if (v := number(row.get(k))) is not None})
            metrics[text_value(key, 100)] = {'percentile': percentile, 'category': text_value(raw.get('category')), 'distributions': distributions}
    return FieldExperience(
        status='available' if metrics else 'unavailable',
        scope='origin' if scope == 'origin' or value.get('origin_fallback') is True else 'page',
        id=text_value(value.get('id')), overall_category=text_value(value.get('overall_category')), metrics=metrics,
    )


def normalize_result(item: PageSpeedObservation, raw: dict) -> PageSpeedObservation:
    lab = mapping(raw.get('lighthouseResult'))
    item.crux_page = field_experience(raw.get('loadingExperience'), 'page')
    item.crux_origin = field_experience(raw.get('originLoadingExperience'), 'origin')
    if not lab or lab.get('runtimeError'):
        item.error = 'lighthouse_runtime_error' if lab else 'missing_lighthouse_result'
        return item
    settings = mapping(lab.get('configSettings'))
    if settings.get('formFactor') not in (None, item.strategy):
        item.error = 'strategy_mismatch'
        return item
    item.final_url = text_value(lab.get('finalUrl'))
    try:
        if lab.get('requestedUrl', item.url) != item.url or origin(item.final_url or item.url) != origin(item.url):
            item.error = 'url_mismatch'
            return item
    except (ValueError, TypeError, AttributeError):
        item.error = 'invalid_url'
        return item
    item.lighthouse_version = text_value(lab.get('lighthouseVersion'), 100)
    item.fetch_time = text_value(lab.get('fetchTime'), 100)
    categories = mapping(lab.get('categories'))
    audits = mapping(lab.get('audits'))
    for category in ('performance', 'seo'):
        category_data = mapping(categories.get(category))
        score = number(category_data.get('score'), maximum=1)
        setattr(item, category + '_score', score * 100 if score is not None else None)
        if score is None:
            item.missing.append(category + '_score')
        refs = category_data.get('auditRefs')
        if not isinstance(refs, list) or not refs:
            item.missing.append(category + '_audits')
            continue
        for ref in refs:
            audit_id = mapping(ref).get('id')
            if not isinstance(audit_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,150}', audit_id):
                item.missing.append(category + '_audit_reference')
                continue
            audit = mapping(audits.get(audit_id))
            mode = audit.get('scoreDisplayMode')
            score = number(audit.get('score'), maximum=1) if mode in {'binary', 'numeric', 'metricSavings'} else None
            if not audit or mode == 'error' or (score is None and mode not in {'manual', 'notApplicable', 'informative'}):
                item.missing.append(audit_id)
            item.audits[audit_id] = LighthouseAudit(
                id=audit_id, category=category, title=text_value(audit.get('title'), 300) or audit_id,
                description=text_value(audit.get('description')) or '', score=score,
                display_value=text_value(audit.get('displayValue'), 500), numeric_value=number(audit.get('numericValue')),
                numeric_unit=text_value(audit.get('numericUnit'), 100),
                failed=score is not None and score < 1 and mode in {'binary', 'numeric', 'metricSavings'},
            )
    for name, (audit_id, unit) in METRICS.items():
        audit = mapping(audits.get(audit_id))
        value = number(audit.get('numericValue')) if audit.get('numericUnit') == unit and audit.get('scoreDisplayMode') != 'error' else None
        item.metrics[name] = value
        if value is None:
            item.missing.append(name)
    item.status = 'incomplete' if item.missing else 'success'
    return item


def collect_pagespeed(config: Config, store: RunStore, observations: list[Observation], *, session: requests.Session | None = None) -> list[PageSpeedObservation]:
    """One request per selected URL/strategy, plus bounded transient retries."""
    if not config.pagespeed.enabled:
        return []
    urls = select_pages(observations, config)
    if not urls:
        return []
    client = session or requests.Session()
    results = []
    quota_deferred = False
    api_key = os.environ.get('PAGESPEED_API_KEY', '')
    try:
        for url in urls:
            for strategy in config.pagespeed.strategies:
                item = PageSpeedObservation(run_id=store.run_id, url=url, strategy=strategy, collected_at=datetime.now(UTC))
                results.append(item)
                if quota_deferred:
                    item.error = 'quota_deferred'
                    continue
                params = {'url': url, 'strategy': strategy, 'category': ['performance', 'seo'], 'locale': 'en'}
                if api_key:
                    params['key'] = api_key
                for attempt in range(config.pagespeed.retries + 1):
                    item.attempts += 1
                    item.error = None
                    delay = 0
                    try:
                        with client.get(ENDPOINT, params=params, timeout=(config.connect_timeout, config.pagespeed.read_timeout), allow_redirects=False, stream=True) as response:
                            item.http_status = response.status_code
                            if response.status_code != 200:
                                item.error = f'http_{response.status_code}'
                                delay = retry_delay(response.headers.get('Retry-After'), attempt)
                                retry = response.status_code in RETRYABLE
                            else:
                                chunks, size = [], 0
                                for chunk in response.iter_content(chunk_size=65536):
                                    size += len(chunk)
                                    if size > MAX_RESPONSE_BYTES:
                                        raise ValueError('response_too_large')
                                    chunks.append(chunk)
                                body = b''.join(chunks)
                                # A key must never enter any saved evidence, even if echoed by upstream.
                                if api_key and api_key in body.decode('utf-8', errors='replace'):
                                    item.error = 'sensitive_response'
                                    break
                                raw = json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('invalid_json')))
                                if not isinstance(raw, dict) or raw.get('error'):
                                    raise ValueError('invalid_response')
                                if api_key and api_key in json.dumps(raw, ensure_ascii=False):
                                    item.error = 'sensitive_response'
                                    break
                                normalize_result(item, raw)
                                # Compact raw audit fields preserve diagnostics without screenshots,
                                # rendered HTML, resource waterfalls, or unbounded DOM detail tables.
                                lab = mapping(raw.get('lighthouseResult'))
                                compact = {
                                    'loadingExperience': item.crux_page.model_dump(mode='json'),
                                    'originLoadingExperience': item.crux_origin.model_dump(mode='json'),
                                }
                                compact['lighthouseResult'] = {
                                    'requestedUrl': item.url, 'finalUrl': item.final_url,
                                    'lighthouseVersion': item.lighthouse_version, 'fetchTime': item.fetch_time,
                                    'runtimeError': item.error,
                                }
                                compact['lighthouseResult']['categories'] = {
                                    key: {'score': number(mapping(value).get('score'), maximum=1), 'auditRefs': [{'id': ref} for ref, audit in item.audits.items() if audit.category == key]}
                                    for key, value in mapping(lab.get('categories')).items() if key in {'performance', 'seo'}
                                }
                                compact['lighthouseResult']['audits'] = {
                                    key: {
                                        **{field: text_value(mapping(mapping(lab.get('audits')).get(key)).get(field)) for field in ('id', 'title', 'description', 'scoreDisplayMode', 'displayValue', 'numericUnit')},
                                        'score': number(mapping(mapping(lab.get('audits')).get(key)).get('score'), maximum=1),
                                        'numericValue': number(mapping(mapping(lab.get('audits')).get(key)).get('numericValue')),
                                    }
                                    for key in sorted(set(item.audits) | {audit_id for audit_id, _ in METRICS.values()})
                                }
                                item.body_path, item.body_sha256 = store.save_diagnostic('pagespeed', json.dumps(compact, ensure_ascii=False, allow_nan=False).encode())
                                break
                    except requests.RequestException as exc:
                        item.error = type(exc).__name__
                        retry, delay = True, float(2 ** attempt)
                    except (ValueError, TypeError, RecursionError):
                        item.error = 'invalid_response'
                        item.status = 'unavailable'
                        break
                    if not retry or attempt == config.pagespeed.retries or delay > 60:
                        if delay > 60:
                            item.error = 'retry_deferred'
                        break
                    time.sleep(max(config.request_interval, delay))
                if item.http_status in {403, 429}:
                    quota_deferred = True
                time.sleep(config.request_interval)
    finally:
        if session is None:
            client.close()
    return results

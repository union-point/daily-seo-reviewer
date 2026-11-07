"""Small origin-bound HTTP client shared by the preflight and future crawler."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urldefrag, urljoin

import requests
from protego import Protego

from seo_reviewer.config import Config, origin
from seo_reviewer.models import FetchEvidence
from seo_reviewer.storage import RunStore

REDIRECTS = {301, 302, 303, 307, 308}
RETRYABLE = {429, 500, 502, 503, 504}
CHALLENGE_MARKERS = (
    b"cf-chl-", b"/cdn-cgi/challenge-platform/", b"<title>just a moment",
    b"<title>access denied", b"<title>attention required", b"<title>captcha",
)


@dataclass
class Fetch:
    evidence: FetchEvidence
    body: bytes

    @property
    def ok(self) -> bool:
        status = self.evidence.status_code
        return self.evidence.error is None and status is not None and 200 <= status < 300


def retry_delay(value: str | None, attempt: int) -> float:
    """Honor Retry-After; callers defer rather than truncate a long delay."""
    if value:
        if value.isdigit():
            return float(value)
        try:
            date = parsedate_to_datetime(value)
            return max(0, (date - datetime.now(UTC)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    return float(2 ** attempt)


class Collector:
    def __init__(self, config: Config, store: RunStore, session: requests.Session | None = None) -> None:
        self.config = config
        self.store = store
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})
        self.robots: Protego | None = None
        self.interval = config.request_interval
        self.next_request = 0.0
        self.fetches: list[FetchEvidence] = []

    def close(self) -> None:
        self.session.close()

    def in_scope(self, url: str) -> bool:
        try:
            return origin(url) == self.config.site_url
        except ValueError:
            return False

    def fetch(self, url: str, *, robots_request: bool = False) -> Fetch:
        url = urldefrag(url)[0]
        evidence = FetchEvidence(
            requested_url=url, final_url=url, fetched_at=datetime.now(UTC)
        )
        started = time.monotonic()
        current = url
        body = b""
        while True:
            evidence.final_url = current
            evidence.status_code = None
            evidence.headers = {}
            if not self.in_scope(current):
                evidence.error = "off_origin"
                break
            if not robots_request and (
                self.robots is None or not self.robots.can_fetch(current, self.config.user_agent)
            ):
                evidence.error = "robots_disallowed" if self.robots else "robots_unavailable"
                break
            if self.interval > 60:
                evidence.error = "robots_rate_deferred"
                break
            for attempt in range(self.config.retries + 1):
                time.sleep(max(0, self.next_request - time.monotonic()))
                self.next_request = time.monotonic() + self.interval
                evidence.attempts += 1
                body = b""
                evidence.error = None
                evidence.status_code = None
                evidence.headers = {}
                request_started = time.monotonic()
                try:
                    with self.session.get(
                        current, allow_redirects=False, stream=True,
                        timeout=(self.config.connect_timeout, self.config.read_timeout),
                    ) as response:
                        evidence.status_code = response.status_code
                        evidence.headers = {
                            key: value for key, value in response.headers.items()
                            if key.lower() in {"content-type", "location", "retry-after", "x-robots-tag"}
                        }
                        chunks = []
                        size = 0
                        for chunk in response.iter_content(chunk_size=65536):
                            size += len(chunk)
                            if size > self.config.max_body_bytes:
                                evidence.error = "response_too_large"
                                break
                            chunks.append(chunk)
                        body = b"".join(chunks)
                except requests.RequestException as exc:
                    # Error class is safe to persist; exception strings can contain credentials.
                    evidence.error = type(exc).__name__
                finally:
                    evidence.response_duration_seconds = (evidence.response_duration_seconds or 0) + time.monotonic() - request_started
                if any(marker in body[:100_000].lower() for marker in CHALLENGE_MARKERS):
                    evidence.error = "challenge_response"
                    break
                if evidence.error == "response_too_large":
                    break
                if not evidence.error and evidence.status_code not in RETRYABLE:
                    break
                if attempt < self.config.retries:
                    delay = retry_delay(self._header(evidence, "retry-after"), attempt)
                    if delay > 60:
                        evidence.error = "retry_deferred"
                        break
                    self.next_request = max(self.next_request, time.monotonic() + delay)
            if evidence.error:
                break
            if any(marker in body[:100_000].lower() for marker in CHALLENGE_MARKERS):
                evidence.error = "challenge_response"
                break
            if evidence.status_code not in REDIRECTS:
                break
            location = self._header(evidence, "location")
            if not location or len(evidence.redirects) >= 5:
                evidence.error = "invalid_redirect" if not location else "too_many_redirects"
                break
            target = urldefrag(urljoin(current, location))[0]
            evidence.redirects.append(target)
            # Preserve each redirect response as well as the final aggregate observation.
            self.store.save_response(evidence.model_copy(deep=True), body)
            current = target
            body = b""
        evidence.response_duration_seconds = round(evidence.response_duration_seconds or 0, 3)
        evidence.duration_seconds = round(time.monotonic() - started, 3)
        self.store.save_response(evidence, body)
        self.fetches.append(evidence)
        return Fetch(evidence, body)

    @staticmethod
    def _header(evidence: FetchEvidence, name: str) -> str | None:
        return next((value for key, value in evidence.headers.items() if key.lower() == name), None)

    def load_robots(self) -> Fetch:
        result = self.fetch(self.config.site_url + "/robots.txt", robots_request=True)
        if result.evidence.error:
            return result
        if result.evidence.status_code in {404, 410}:
            self.robots = Protego.parse("")
        elif result.ok:
            text = result.body.decode("utf-8-sig", errors="replace")
            if "<html" in text.lower() or "<!doctype html" in text.lower():
                return result  # A soft error/challenge is not an empty robots policy.
            self.robots = Protego.parse(text)
            delay = self.robots.crawl_delay(self.config.user_agent)
            rate = self.robots.request_rate(self.config.user_agent)
            self.interval = max(self.interval, float(delay or 0))
            if rate:
                # Spacing an entire window apart is conservative for rolling rate limits.
                self.interval = max(self.interval, float(rate.seconds))
            self.next_request = max(self.next_request, time.monotonic() + self.interval)
        return result

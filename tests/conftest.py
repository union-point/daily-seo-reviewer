from types import SimpleNamespace

import pytest
import requests

from seo_reviewer.collection import Collector
from seo_reviewer.config import Config
from seo_reviewer.storage import RunStore


def response(status=200, body=b"", **headers):
    result = requests.Response()
    result.status_code = status
    result._content = body
    result._content_consumed = True
    result.headers.update(headers)
    return result


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        pass


@pytest.fixture
def clock(monkeypatch):
    state = SimpleNamespace(now=100.0, sleeps=[])

    def sleep(seconds):
        state.sleeps.append(seconds)
        state.now += seconds

    monkeypatch.setattr("seo_reviewer.collection.time", SimpleNamespace(
        monotonic=lambda: state.now, sleep=sleep,
    ))
    return state


@pytest.fixture
def make_collector(tmp_path, clock):
    def make(responses, **overrides):
        config = Config(site_url="https://example.com", data_dir=tmp_path, **overrides)
        session = FakeSession(responses)
        return Collector(config, RunStore(tmp_path), session), session
    return make

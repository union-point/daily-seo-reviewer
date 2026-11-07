from datetime import UTC, datetime

import pytest

from seo_reviewer.models import FetchEvidence
from seo_reviewer.storage import RunStore


def test_existing_run_cannot_be_overwritten(tmp_path):
    store = RunStore(tmp_path, "existing-run")
    evidence = FetchEvidence(requested_url="https://example.com", final_url="https://example.com", fetched_at=datetime.now(UTC))
    store.save_response(evidence, b"original")
    with pytest.raises(FileExistsError):
        RunStore(tmp_path, "existing-run")
    assert (store.path / evidence.body_path).read_bytes() == b"original"


@pytest.mark.parametrize("run_id", ["../escape", "..", ".", "", "/absolute"])
def test_run_id_cannot_escape_data_directory(tmp_path, run_id):
    with pytest.raises(ValueError):
        RunStore(tmp_path, run_id)

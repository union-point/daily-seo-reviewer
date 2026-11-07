"""Create immutable evidence snapshots without updating baseline state."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from seo_reviewer.models import FetchEvidence, Preflight


class RunStore:
    def __init__(self, data_dir: Path, run_id: str | None = None) -> None:
        self.run_id = run_id if run_id is not None else (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid4().hex[:8]
        )
        if not self.run_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for c in self.run_id) or self.run_id in {".", ".."}:
            raise ValueError("Invalid run ID")
        self.path = data_dir / "runs" / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "responses").mkdir()

    def save_response(self, evidence: FetchEvidence, body: bytes) -> None:
        """Persist raw bytes and their digest before appending evidence metadata."""
        if any((self.path / name).exists() for name in ("preflight.json", "collection.json")):
            raise FileExistsError("Run is already finalized")
        relative = Path("responses") / f"{uuid4().hex}.body"
        with (self.path / relative).open("xb") as output:
            output.write(body)
        evidence.body_path = relative.as_posix()
        evidence.body_sha256 = hashlib.sha256(body).hexdigest()
        with (self.path / "fetches.jsonl").open("a", encoding="utf-8") as output:
            output.write(evidence.model_dump_json() + "\n")

    def save_preflight(self, result: Preflight) -> None:
        with (self.path / "preflight.json").open("x", encoding="utf-8") as output:
            output.write(result.model_dump_json(indent=2) + "\n")

    def save_diagnostic(self, kind: str, body: bytes) -> tuple[str, str]:
        """Save compact, non-executable external diagnostics before finalization."""
        if kind != 'pagespeed':
            raise ValueError('Unknown diagnostic kind')
        if any((self.path / name).exists() for name in ('preflight.json', 'collection.json')):
            raise FileExistsError('Run is already finalized')
        directory = self.path / kind
        directory.mkdir(exist_ok=True)
        relative = Path(kind) / (uuid4().hex + '.json')
        with (self.path / relative).open('xb') as output:
            output.write(body)
        return relative.as_posix(), hashlib.sha256(body).hexdigest()


def publish_probe(result: Preflight, directory: Path) -> None:
    """Export only JSON for the Pages smoke test; HTML reviews come later."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "preflight.json").write_text(
        result.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    (directory / "index.txt").write_text(
        "Daily SEO Reviewer integration preflight. See preflight.json.\n"
        "This is connectivity evidence, not an SEO review.\n",
        encoding="utf-8",
    )
    (directory / ".nojekyll").touch()

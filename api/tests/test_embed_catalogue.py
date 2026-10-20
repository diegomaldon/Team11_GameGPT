"""scripts/embed_catalogue.py: the command that runs the embedding pipeline (TM11-39).

The pipeline is faked; these check the exit codes, the flags and the report file.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest

from api.services.embedding import EmbeddingModelError
from api.services.embedding_pipeline import EmbeddingRunReport

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "embed_catalogue.py"


def load_script():
    spec = importlib.util.spec_from_file_location("embed_catalogue", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def finished_report(*, failed: int = 0) -> EmbeddingRunReport:
    return EmbeddingRunReport(
        model="fake/model",
        games_to_embed=3,
        embedded_count=3 - failed,
        failed_game_ids=[uuid4() for _ in range(failed)],
        catalogue_count=3,
        embedded_total=3 - failed,
    )


@pytest.fixture
def script(monkeypatch):
    module = load_script()
    calls: dict = {}

    class FakePipeline:
        def __init__(self, embedder, *, batch_size):
            calls["batch_size"] = batch_size

        async def run(self, *, re_embed_all=False):
            calls["re_embed_all"] = re_embed_all
            if "error" in calls:
                raise calls["error"]
            return calls.get("report", finished_report())

    monkeypatch.setattr(module, "has_db", lambda: True)
    monkeypatch.setattr(module, "EmbeddingPipeline", FakePipeline)
    module.calls = calls
    return module


def test_a_complete_run_exits_0_and_writes_the_report(script, tmp_path):
    exit_code = script.main(["--report-dir", str(tmp_path)])

    assert exit_code == 0
    [report_file] = tmp_path.glob("*/embedding_report.json")
    report = json.loads(report_file.read_text())
    assert report["embedded_total"] == 3
    assert report["is_complete"] is True


def test_a_run_with_failures_exits_1(script, tmp_path):
    script.calls["report"] = finished_report(failed=1)
    assert script.main(["--report-dir", str(tmp_path)]) == 1


def test_a_model_that_cannot_load_exits_1_with_a_clear_message(script, tmp_path, capsys):
    script.calls["error"] = EmbeddingModelError("could not load fake/model")

    assert script.main(["--report-dir", str(tmp_path)]) == 1
    assert "could not load" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []


def test_no_database_exits_2_without_running(script, monkeypatch, tmp_path):
    monkeypatch.setattr(script, "has_db", lambda: False)

    assert script.main(["--report-dir", str(tmp_path)]) == 2
    assert "re_embed_all" not in script.calls


def test_flags_reach_the_pipeline(script, tmp_path):
    script.main(["--all", "--batch-size", "8", "--report-dir", str(tmp_path)])
    assert script.calls == {"batch_size": 8, "re_embed_all": True}


@pytest.mark.parametrize("batch_size", ["0", "-3", "ten"])
def test_a_bad_batch_size_is_refused(script, batch_size):
    with pytest.raises(SystemExit):
        script.main(["--batch-size", batch_size])

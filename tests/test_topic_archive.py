import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
import web_dashboard
from cleanup_data import archive_topic


def make_run(data, slug, run_id, topic):
    folder = data / "runs" / slug / run_id
    folder.mkdir(parents=True)
    (folder / "opportunities.json").write_text(
        json.dumps({"topic": topic, "run_id": run_id, "opportunities": []}),
        encoding="utf-8",
    )
    (folder / "results.json").write_text("{}", encoding="utf-8")
    return folder


def test_archive_only_one_exact_topic_and_can_preview(tmp_path):
    data = tmp_path / "data"
    digilocker = make_run(data, "digilocker", "20261010T010000000000Z", "DigiLocker")
    digilocker2 = make_run(data, "digilocker", "20261010T020000000000Z", "DigiLocker")
    pan = make_run(data, "pan", "20261010T030000000000Z", "PAN")
    related = make_run(data, "digilocker-api", "20261010T040000000000Z", "DigiLocker API")
    preview = archive_topic(data, "DigiLocker", confirm=False)
    assert preview["run_count"] == 2
    assert digilocker.is_dir() and digilocker2.is_dir()
    archived = archive_topic(data, "DigiLocker", confirm=True)
    assert archived["run_count"] == 2
    assert not digilocker.exists() and not digilocker2.exists()
    assert pan.is_dir() and related.is_dir()
    assert (data / "topic_trash" / "digilocker" / digilocker.name / "results.json").exists()


def test_archive_rejects_wrong_root(tmp_path):
    with pytest.raises(ValueError):
        archive_topic(tmp_path / "something", "DigiLocker", confirm=True)


def test_topic_api_requires_exact_confirmation(monkeypatch, tmp_path):
    data = tmp_path / "data"
    make_run(data, "digilocker", "20261010T010000000000Z", "DigiLocker")
    monkeypatch.setattr(web_dashboard, "BASE", tmp_path)
    client = TestClient(web_dashboard.app)
    preview = client.post("/api/data/topic/preview", json={"topic": "DigiLocker"})
    assert preview.status_code == 200
    assert preview.json()["run_count"] == 1
    bad = client.post("/api/data/topic/archive", json={
        "topic": "DigiLocker", "confirm_topic": "PAN"
    })
    assert bad.status_code == 400
    result = client.post("/api/data/topic/archive", json={
        "topic": "DigiLocker", "confirm_topic": "DigiLocker"
    })
    assert result.status_code == 200
    assert result.json()["run_count"] == 1

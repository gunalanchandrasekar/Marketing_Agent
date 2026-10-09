from pathlib import Path
from cleanup_data import cleanup

def test_preview_and_confirm_only_generated_data(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "runs" / "digilocker").mkdir(parents=True)
    (root / "runs" / "digilocker" / "x.json").write_text("{}")
    (root / "results.json").write_text("{}")
    (root / "keep.txt").write_text("keep")
    targets = cleanup(root, confirm=False)
    assert len(targets) == 2
    assert (root / "runs").exists()
    cleanup(root, confirm=True)
    assert not (root / "runs").exists()
    assert not (root / "results.json").exists()
    assert (root / "keep.txt").read_text() == "keep"

def test_wrong_cleanup_folder_is_rejected(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        cleanup(tmp_path, confirm=True)

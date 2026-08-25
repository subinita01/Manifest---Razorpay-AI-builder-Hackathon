from core.run_manifest import build_run_manifest


def test_build_run_manifest_populates_all_fields():
    manifest = build_run_manifest("run_1", seed=42)
    assert manifest.run_id == "run_1"
    assert manifest.seed == 42
    assert manifest.config_hash != ""
    assert "pydantic" in manifest.library_versions
    # git_sha may be None outside a repo, but this project *is* a repo.
    assert manifest.git_sha is not None
    assert len(manifest.git_sha) == 40


def test_config_hash_changes_when_config_changes(tmp_path, monkeypatch):
    import core.run_manifest as run_manifest_module

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "a.yaml").write_text("x: 1\n")
    monkeypatch.setattr(run_manifest_module, "CONFIG_DIR", config_dir)
    hash_before = run_manifest_module._config_hash()

    (config_dir / "a.yaml").write_text("x: 2\n")
    hash_after = run_manifest_module._config_hash()

    assert hash_before != hash_after

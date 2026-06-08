"""Tests for launcher logic that needs no GUI (study resolution at launch)."""

from __future__ import annotations

from smacc.launcher import resolve_initial_study
from smacc.study import Study


def test_resolve_initial_study_opens_last_used(tmp_path):
    studies = tmp_path / "studies"
    studies.mkdir()
    existing = Study.create(studies, "alpha")
    study = resolve_initial_study({"last_study": str(existing.root)}, studies)
    assert study.root == existing.root


def test_resolve_initial_study_falls_back_to_default(tmp_path):
    studies = tmp_path / "studies"
    studies.mkdir()
    study = resolve_initial_study({"last_study": None}, studies)
    assert study.name == "default"
    assert study.cues_dir.is_dir()


def test_resolve_initial_study_ignores_missing_last_study(tmp_path):
    studies = tmp_path / "studies"
    studies.mkdir()
    study = resolve_initial_study({"last_study": str(tmp_path / "gone")}, studies)
    assert study.name == "default"  # stale path ignored, default used

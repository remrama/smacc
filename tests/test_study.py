"""Tests for the Study workspace: paths, scaffolding, and the default study."""

from __future__ import annotations

import pytest

from smacc import utils
from smacc.study import CONFIG_NAME, Study, default_study


def test_study_paths_are_rooted_under_the_folder(tmp_path):
    study = Study(tmp_path / "my-study")
    assert study.name == "my-study"
    assert study.config_path == tmp_path / "my-study" / CONFIG_NAME
    assert study.cues_dir == tmp_path / "my-study" / "cues"
    assert study.sessions_dir == tmp_path / "my-study" / "sessions"


def test_open_creates_subfolders_and_is_lenient_without_config(tmp_path):
    study = Study.open(tmp_path / "s")
    assert study.cues_dir.is_dir()
    assert study.sessions_dir.is_dir()
    assert not study.has_config()  # a folder without study.smacc is still valid


def test_create_scaffolds_tree_and_seeds_demo_cues(tmp_path):
    study = Study.create(tmp_path, "trial")
    assert study.root == tmp_path / "trial"
    assert study.cues_dir.is_dir()
    assert study.sessions_dir.is_dir()
    for name in utils.DEMO_CUES:  # demos seeded into the study's own cues/
        assert (study.cues_dir / name).is_file()


def test_create_refuses_to_clobber_an_existing_study(tmp_path):
    Study.create(tmp_path, "dup")
    with pytest.raises(FileExistsError):
        Study.create(tmp_path, "dup")


def test_has_config_true_when_config_present(tmp_path):
    study = Study.open(tmp_path / "s")
    study.config_path.write_text("kind: smacc/settings\n", encoding="utf-8")
    assert study.has_config()


def test_default_study_creates_then_reopens(tmp_path):
    studies = tmp_path / "studies"
    studies.mkdir()
    first = default_study(studies)
    assert first.root == studies / "default"
    assert first.cues_dir.is_dir()
    # A later launch opens the existing folder rather than raising on re-create.
    second = default_study(studies)
    assert second.root == first.root

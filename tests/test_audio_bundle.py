"""Tests for the audio panel's study file-bundling hooks (no GUI required).

``relativize_files`` / ``resolve_files`` operate only on the passed ``state``
dict and ``study_dir``; they don't touch ``self``, so they can be exercised
with a throwaway instance via ``__new__`` (avoids constructing the Qt window).
"""

from smacc.panels.audio import AudioCueWindow


def _panel():
    return AudioCueWindow.__new__(AudioCueWindow)


def test_relativize_copies_and_rewrites_to_basename(tmp_path):
    cue = tmp_path / "tone.wav"
    cue.write_bytes(b"RIFF....")
    study_dir = tmp_path / "study"
    study_dir.mkdir()
    state = {"cues": [{"name": "Cue", "file": str(cue), "volume": 0.2, "loop": False}]}

    _panel().relativize_files(state, study_dir)

    assert (study_dir / "tone.wav").is_file()  # copied into the bundle
    assert state["cues"][0]["file"] == "tone.wav"  # rewritten to basename


def test_resolve_rewrites_basename_to_absolute(tmp_path):
    study_dir = tmp_path / "study"
    study_dir.mkdir()
    (study_dir / "tone.wav").write_bytes(b"RIFF....")
    state = {
        "cues": [{"name": "Cue", "file": "tone.wav", "volume": 0.2, "loop": False}]
    }

    _panel().resolve_files(state, study_dir)

    assert state["cues"][0]["file"] == str(study_dir / "tone.wav")


def test_relativize_ignores_empty_or_missing_files(tmp_path):
    study_dir = tmp_path / "study"
    study_dir.mkdir()
    state = {
        "cues": [
            {"name": "Empty", "file": "", "volume": 0.2, "loop": False},
            {"name": "Missing", "file": str(tmp_path / "nope.wav"), "volume": 0.2},
        ]
    }

    _panel().relativize_files(state, study_dir)

    assert state["cues"][0]["file"] == ""  # left as-is
    assert state["cues"][1]["file"] == str(tmp_path / "nope.wav")  # not rewritten

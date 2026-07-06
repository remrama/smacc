"""Tests for the YASA automated-staging wrapper, model, and sidecars (#226).

Pure and GUI-free, mirroring test_eeg_staging.py. YASA itself is never installed
here: the wrapper is exercised with a fake ``yasa`` module injected into
``sys.modules`` (the lazy ``import yasa`` inside the function resolves to it), and
the sidecar/model paths need no YASA at all — the same split that lets the frozen
binary display an overlay without bundling YASA.
"""

from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smacc.config import VERSION
from smacc.eeg import staging, yasa_staging

# ----- the model ------------------------------------------------------------


def test_aasm_stage_order_matches_the_manual_vocabulary():
    # The probability-vector order and the manual AASM vocabulary must agree, so
    # the overlay colours line up with staging.AASM without re-deriving anything.
    assert yasa_staging.AASM_STAGES == staging.AASM.stages
    assert yasa_staging.EPOCH_SECONDS == 30.0


def test_channel_roles_require_an_eeg_channel():
    with pytest.raises(ValueError, match="EEG channel is required"):
        yasa_staging.ChannelRoles("")
    roles = yasa_staging.ChannelRoles("C4")
    assert roles.eog is None and roles.emg is None


def test_epoch_rounds_and_exposes_confidence():
    epoch = yasa_staging.AutoStageEpoch(
        0.0004, 30.0, "N2", (0.1, 0.05, 0.8000004, 0.02, 0.03)
    )
    assert epoch.onset == 0.0  # rounded to ms
    assert epoch.proba[2] == 0.8  # rounded to 6 dp
    assert epoch.confidence == 0.8  # the winning class's probability


def test_epoch_rejects_a_non_aasm_stage_and_a_short_vector():
    with pytest.raises(ValueError, match="not an AASM stage"):
        yasa_staging.AutoStageEpoch(0.0, 30.0, "S2", (0.2,) * 5)
    with pytest.raises(ValueError, match="proba needs 5 values"):
        yasa_staging.AutoStageEpoch(0.0, 30.0, "W", (0.5, 0.5))


def test_epoch_at_resolves_by_absolute_time_end_exclusive():
    epochs = [
        yasa_staging.AutoStageEpoch(0.0, 30.0, "W", (0.9, 0.02, 0.03, 0.02, 0.03)),
        yasa_staging.AutoStageEpoch(30.0, 30.0, "N1", (0.1, 0.6, 0.1, 0.1, 0.1)),
    ]
    assert yasa_staging.epoch_at(epochs, 15.0).stage == "W"
    assert yasa_staging.epoch_at(epochs, 30.0).stage == "N1"  # boundary → next
    assert yasa_staging.epoch_at(epochs, 90.0) is None


# ----- sidecar paths (reserved namespace) -----------------------------------


def test_sidecar_paths_use_the_reserved_autostage_namespace():
    tsv, js = yasa_staging.autostage_sidecar_paths("/data/night1.edf")
    assert tsv == Path("/data/night1.autostage.tsv")
    assert js == Path("/data/night1.autostage.json")


def test_autostage_paths_cannot_collide_with_a_manual_rater():
    # The whole point of the reserved namespace: a rater literally named "yasa"
    # writes night1.stages.yasa.tsv, which must NOT be the automated sidecar.
    auto_tsv, _ = yasa_staging.autostage_sidecar_paths("night1.edf")
    rater_tsv, _ = staging.rater_stages_paths("night1.edf", "yasa")
    assert auto_tsv != rater_tsv
    assert auto_tsv.name == "night1.autostage.tsv"
    assert rater_tsv.name == "night1.stages.yasa.tsv"


# ----- sidecar I/O ----------------------------------------------------------


def _hypnogram() -> yasa_staging.AutoStageHypnogram:
    return yasa_staging.AutoStageHypnogram(
        epochs=(
            yasa_staging.AutoStageEpoch(0.0, 30.0, "W", (0.8, 0.1, 0.05, 0.0, 0.05)),
            yasa_staging.AutoStageEpoch(30.0, 30.0, "N2", (0.1, 0.2, 0.5, 0.1, 0.1)),
            yasa_staging.AutoStageEpoch(60.0, 30.0, "R", (0.05, 0.0, 0.05, 0.0, 0.9)),
        ),
        channels=yasa_staging.ChannelRoles("C4", "EOG", "EMG"),
        yasa_version="0.6.5",
        source_sfreq=256.0,
        source_duration=90.0,
    )


def test_tsv_writes_the_winning_stage_per_epoch(tmp_path: Path):
    path = tmp_path / "night1.autostage.tsv"
    yasa_staging.write_autostage_tsv(_hypnogram().epochs, path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "onset\tduration\tstage"
    assert lines[1] == "0.000\t30.000\tW"
    assert lines[3] == "60.000\t30.000\tR"


def test_json_round_trips_the_full_probability_matrix(tmp_path: Path):
    path = tmp_path / "night1.autostage.json"
    original = _hypnogram()
    yasa_staging.write_autostage_json(
        path,
        original,
        source_name="night1.edf",
        meas_date=datetime(2026, 6, 5, 22, 0, tzinfo=UTC),
    )
    reloaded = yasa_staging.read_autostage_json(path)
    assert reloaded.epochs == original.epochs
    assert reloaded.channels == original.channels
    assert reloaded.yasa_version == "0.6.5"
    assert reloaded.source_sfreq == 256.0


def test_json_records_provenance_for_staleness_checks(tmp_path: Path):
    path = tmp_path / "night1.autostage.json"
    yasa_staging.write_autostage_json(
        path, _hypnogram(), source_name="night1.edf", meas_date=None
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "smacc/eeg-autostage"
    assert payload["ScoringManual"] == "AASM"
    assert payload["Stages"] == ["W", "N1", "N2", "N3", "R"]
    assert payload["Channels"] == {"eeg": "C4", "eog": "EOG", "emg": "EMG"}
    assert payload["SourceSampleRate"] == 256.0
    assert payload["SourceDuration"] == 90.0
    assert payload["MeasurementDate"] is None
    assert payload["GeneratedBy"] == {
        "Name": "SMACC",
        "Version": VERSION,
        "YASA": "0.6.5",
    }


def test_read_json_rejects_a_foreign_file(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"kind": "something-else"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Not a SMACC autostage sidecar"):
        yasa_staging.read_autostage_json(path)


def test_read_json_rejects_non_json(tmp_path: Path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Not valid JSON"):
        yasa_staging.read_autostage_json(path)


def test_read_json_rejects_a_newer_schema_version(tmp_path: Path):
    # A sidecar from a future SMACC must be refused with a clear message, not
    # silently misread — matching the settings/surveys readers.
    path = tmp_path / "night1.autostage.json"
    yasa_staging.write_autostage_json(
        path, _hypnogram(), source_name="night1.edf", meas_date=None
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = yasa_staging.SCHEMA_VERSION + 1
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="newer than this SMACC"):
        yasa_staging.read_autostage_json(path)


def test_read_json_tolerates_a_notepad_bom(tmp_path: Path):
    path = tmp_path / "night1.autostage.json"
    yasa_staging.write_autostage_json(
        path, _hypnogram(), source_name="night1.edf", meas_date=None
    )
    # Re-save with a BOM, as Notepad would.
    path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8-sig")
    assert yasa_staging.read_autostage_json(path).epochs == _hypnogram().epochs


# ----- yasa_available -------------------------------------------------------


def test_yasa_available_reflects_find_spec(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(yasa_staging, "find_spec", lambda name: object())
    assert yasa_staging.yasa_available() is True
    monkeypatch.setattr(yasa_staging, "find_spec", lambda name: None)
    assert yasa_staging.yasa_available() is False


def test_run_raises_when_yasa_is_absent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(yasa_staging, "yasa_available", lambda: False)
    with pytest.raises(RuntimeError, match="not installed"):
        yasa_staging.run_yasa_staging(_FakeRecording(), eeg="C4")


# ----- run_yasa_staging with YASA mocked ------------------------------------


class _FakeRaw:
    """The minimal MNE-Raw surface run_yasa_staging touches (copy→pick→load)."""

    def __init__(self) -> None:
        self.picked: list[str] | None = None

    def copy(self) -> _FakeRaw:
        return self

    def pick(self, picks: list[str]) -> _FakeRaw:
        self.picked = list(picks)
        return self

    def load_data(self, verbose: str | None = None) -> _FakeRaw:
        return self


class _FakeRecording:
    def __init__(self) -> None:
        self._raw = _FakeRaw()
        self.ch_names = ["C4", "EOG", "EMG", "junk"]
        self.sfreq = 256.0
        self.duration = 90.0


class _FakeProba:
    """A stand-in for YASA's proba DataFrame (no pandas dependency)."""

    def __init__(self, columns: list[str], rows: list[dict[str, float]]) -> None:
        self.columns = columns
        self._rows = rows

    def iterrows(self):
        yield from enumerate(self._rows)


class _FakeHypnogram:
    """yasa >= 0.7's predict() return: a Hypnogram exposing per-epoch `.proba`."""

    def __init__(self, proba: _FakeProba) -> None:
        self.proba = proba


def _install_fake_yasa(
    monkeypatch: pytest.MonkeyPatch, *, proba: _FakeProba, via_hypnogram: bool = True
) -> dict[str, object]:
    """Install a fake ``yasa`` whose SleepStaging returns ``proba``.

    ``via_hypnogram`` models yasa >= 0.7 (predict() → Hypnogram with ``.proba``);
    ``False`` models the older path where predict() has no ``.proba`` and the
    probabilities come from predict_proba() instead.
    """
    captured: dict[str, object] = {}

    class FakeSleepStaging:
        def __init__(self, raw, *, eeg_name, eog_name=None, emg_name=None) -> None:
            captured["raw"] = raw
            captured["kwargs"] = {
                "eeg_name": eeg_name,
                "eog_name": eog_name,
                "emg_name": emg_name,
            }

        def predict(self):
            captured["predict_called"] = True
            return _FakeHypnogram(proba) if via_hypnogram else object()

        def predict_proba(self):
            captured["predict_proba_called"] = True
            return proba

    module = types.ModuleType("yasa")
    module.SleepStaging = FakeSleepStaging
    module.__version__ = "9.9.9-fake"
    monkeypatch.setitem(sys.modules, "yasa", module)
    monkeypatch.setattr(yasa_staging, "yasa_available", lambda: True)
    return captured


# yasa >= 0.7 relabels the probability columns W→WAKE, R→REM (verified in
# SleepStaging.predict); these are the real column headers we normalize.
def _proba(*rows: dict[str, float]) -> _FakeProba:
    return _FakeProba(["WAKE", "N1", "N2", "N3", "REM"], list(rows))


def test_run_passes_channel_names_and_crops_to_them(monkeypatch: pytest.MonkeyPatch):
    captured = _install_fake_yasa(
        monkeypatch,
        proba=_proba({"WAKE": 0.9, "N1": 0.1, "N2": 0.0, "N3": 0.0, "REM": 0.0}),
    )
    recording = _FakeRecording()
    result = yasa_staging.run_yasa_staging(recording, eeg="C4", eog="EOG", emg="EMG")
    assert captured["kwargs"] == {
        "eeg_name": "C4",
        "eog_name": "EOG",
        "emg_name": "EMG",
    }
    # Only the chosen channels are cropped in (never the whole montage).
    assert recording._raw.picked == ["C4", "EOG", "EMG"]
    assert result.channels == yasa_staging.ChannelRoles("C4", "EOG", "EMG")
    assert result.yasa_version == "9.9.9-fake"
    assert result.source_sfreq == 256.0
    # The Hypnogram's own probabilities are used; the deprecated predict_proba() is
    # never called on the >= 0.7 path.
    assert captured.get("predict_proba_called") is None


def test_run_reorders_probabilities_and_takes_the_argmax_stage(
    monkeypatch: pytest.MonkeyPatch,
):
    # Columns come relabelled and unordered (WAKE,N1,N2,N3,REM); each epoch vector
    # must come back in AASM order (W,N1,N2,N3,R), and the winning stage is the
    # vector's argmax — so stage and probabilities can never disagree.
    _install_fake_yasa(
        monkeypatch,
        proba=_proba(
            {"WAKE": 0.7, "N1": 0.1, "N2": 0.2, "N3": 0.0, "REM": 0.0},
            {"WAKE": 0.05, "N1": 0.1, "N2": 0.6, "N3": 0.2, "REM": 0.05},
        ),
    )
    result = yasa_staging.run_yasa_staging(_FakeRecording(), eeg="C4")
    first, second = result.epochs
    assert (first.onset, first.duration, first.stage) == (0.0, 30.0, "W")
    assert first.proba == (0.7, 0.1, 0.2, 0.0, 0.0)  # W,N1,N2,N3,R
    assert (second.onset, second.stage) == (30.0, "N2")
    assert second.proba == (0.05, 0.1, 0.6, 0.2, 0.05)


def test_run_normalizes_wake_and_rem_columns(monkeypatch: pytest.MonkeyPatch):
    # The WAKE/REM column headers must land in the W and R slots of the vector.
    _install_fake_yasa(
        monkeypatch,
        proba=_proba(
            {"WAKE": 0.9, "N1": 0.1, "N2": 0.0, "N3": 0.0, "REM": 0.0},
            {"WAKE": 0.0, "N1": 0.0, "N2": 0.0, "N3": 0.1, "REM": 0.9},
        ),
    )
    result = yasa_staging.run_yasa_staging(_FakeRecording(), eeg="C4")
    assert [e.stage for e in result.epochs] == ["W", "R"]
    assert result.epochs[0].proba == (0.9, 0.1, 0.0, 0.0, 0.0)
    assert result.epochs[1].proba == (0.0, 0.0, 0.0, 0.1, 0.9)


def test_run_falls_back_to_predict_proba_on_older_yasa(monkeypatch: pytest.MonkeyPatch):
    # If predict() returns no Hypnogram (.proba absent), the probabilities come
    # from predict_proba() instead — the older-yasa path stays supported.
    captured = _install_fake_yasa(
        monkeypatch,
        proba=_FakeProba(
            ["N1", "N2", "N3", "R", "W"],  # older builds keep the W/R headers
            [{"N1": 0.0, "N2": 0.0, "N3": 0.0, "R": 0.0, "W": 1.0}],
        ),
        via_hypnogram=False,
    )
    result = yasa_staging.run_yasa_staging(_FakeRecording(), eeg="C4")
    assert captured["predict_proba_called"] is True
    assert result.epochs[0].stage == "W"
    assert result.epochs[0].proba == (1.0, 0.0, 0.0, 0.0, 0.0)


def test_run_dedupes_a_channel_serving_two_roles(monkeypatch: pytest.MonkeyPatch):
    # One channel can fill two roles (no separate EOG): pick() must not see a
    # duplicate, but YASA still gets the (repeated) role names.
    captured = _install_fake_yasa(
        monkeypatch,
        proba=_proba({"WAKE": 1.0, "N1": 0.0, "N2": 0.0, "N3": 0.0, "REM": 0.0}),
    )
    recording = _FakeRecording()
    yasa_staging.run_yasa_staging(recording, eeg="C4", eog="C4")
    assert recording._raw.picked == ["C4"]  # deduped
    assert captured["kwargs"] == {"eeg_name": "C4", "eog_name": "C4", "emg_name": None}


def test_run_rejects_a_channel_not_in_the_recording(monkeypatch: pytest.MonkeyPatch):
    _install_fake_yasa(
        monkeypatch,
        proba=_proba({"WAKE": 1.0, "N1": 0.0, "N2": 0.0, "N3": 0.0, "REM": 0.0}),
    )
    with pytest.raises(ValueError, match="not in the recording"):
        yasa_staging.run_yasa_staging(_FakeRecording(), eeg="Fpz")


# ----- import hygiene -------------------------------------------------------


def test_importing_the_wrapper_never_imports_yasa():
    # The module must lazy-import yasa (and its heavy tree) so importing it — and
    # the display path that reads its sidecars — never pulls YASA into a frozen
    # session build. A future edit that hoists the import to module scope breaks
    # the source-only fallback; this guard catches it (mirrors the session-stack
    # isolation check in test_eeg_window.py).
    code = (
        "import sys; import smacc.eeg.yasa_staging; "
        "leaks = [m for m in ('yasa', 'lightgbm', 'numba', 'llvmlite') "
        "if m in sys.modules]; "
        "sys.exit('leaked: ' + ', '.join(leaks) if leaks else 0)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr

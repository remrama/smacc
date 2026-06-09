"""Headless-GUI setup and shared fixtures for the SMACC test suite.

GUI tests run with no display by forcing Qt's "offscreen" platform *before* any
Qt import (pytest-qt imports Qt the first time its ``qtbot``/``qapp`` fixtures run,
so this module — imported by pytest at collection — is the right place). pytest-qt
then supplies ``qtbot``/``qapp`` and owns the ``QApplication`` lifecycle.

Three things would otherwise make these tests non-deterministic, hang, or crash:

* **Hardware enumeration.** ``DevicesWindow`` (and thus the whole ``SmaccWindow``)
  fills its combos from :func:`smacc.panels.devices.wasapi_devices` /
  ``blinkstick_devices`` at construction, which query sounddevice/BlinkStick. The
  ``mock_devices`` fixture stubs both with fixed device lists.
* **Blocking modal popups.** A few paths call the static ``QMessageBox`` /
  ``QInputDialog`` helpers, which block on a real event loop. ``silence_dialogs``
  replaces them with non-blocking stubs.
* **Nondeterministic Qt object destruction.** Without a running ``exec()`` loop,
  ``deleteLater()`` is never serviced (``processEvents()`` skips DeferredDelete
  events), so test windows died only whenever Python's GC collected their
  wrappers — occasionally mid-event-dispatch in a *later* test, crashing the run
  with a native access violation. ``_deterministic_qt_teardown`` flushes the
  deferred-delete queue and collects garbage at a quiet point after every test.
"""

from __future__ import annotations

import gc
import os

# Must run before PyQt6 is imported anywhere. ``setdefault`` lets a developer
# export QT_QPA_PLATFORM=windows (etc.) to actually watch a test render locally.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import QtCore, QtWidgets

from smacc import devices
from smacc.session import SmaccSession

# Device strings the mock enumeration advertises. Window/settings tests bind roles
# to these exact strings so a loaded study resolves them (no "missing device"
# notice). These are bare names (no ", Windows WASAPI"), matching what
# ``wasapi_devices`` now returns; backward-compat with the old suffixed form is
# covered explicitly in the device/util tests.
FAKE_OUTPUTS = ["Speakers (USB Audio)", "Headphones"]
FAKE_INPUTS = ["Microphone (USB Audio)"]
FAKE_BLINKSTICKS = [("BlinkStick Square BS012345", "BS012345")]


@pytest.fixture(autouse=True)
def _deterministic_qt_teardown():
    """Destroy pending Qt objects at a known-quiet point after every test.

    pytest-qt pumps ``processEvents()`` between tests, but that never services
    ``DeferredDelete`` events — only a running ``exec()`` loop or an explicit
    ``sendPostedEvents`` does. So every ``deleteLater()`` (including the one
    pytest-qt itself issues for each ``qtbot.addWidget`` window at teardown)
    used to pile up, and the C++ side of those widgets died only when Python's
    GC happened to collect their wrappers — sometimes in the middle of a later
    test's event dispatch, which intermittently crashed the suite with a native
    access violation (first seen in the cue-designer tests: the first *shown*
    windows of a run, with row widgets also queued for deferred deletion).

    Teardown order makes this the right spot: pytest-qt queues its
    ``deleteLater`` calls before fixture finalization, and an autouse fixture
    with no dependencies finalizes after the test's other fixtures — so the
    flush runs once everything has been queued, while no dispatch is in flight.
    """
    yield
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.processEvents()
        app.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
        app.processEvents()
        # Reap any wrappers the test left unreferenced (cheap: the young
        # generations hold this test's garbage) so sip can't destroy their C++
        # side later, mid-dispatch. A full collect here costs ~40 ms per test —
        # 4x the whole suite — for no extra safety the loops could measure.
        gc.collect(generation=1)


@pytest.fixture
def mock_devices(monkeypatch):
    """Stub the only construction-time hardware access: device enumeration.

    Returns the advertised devices so a test can bind roles to known strings.
    """
    from smacc.panels import devices as devices_panel

    def fake_wasapi_devices(kind: str) -> list[str]:
        return list(FAKE_INPUTS) if kind == devices.INPUT else list(FAKE_OUTPUTS)

    monkeypatch.setattr(devices_panel, "wasapi_devices", fake_wasapi_devices)
    monkeypatch.setattr(
        devices_panel, "blinkstick_devices", lambda: list(FAKE_BLINKSTICKS)
    )
    return {
        "outputs": list(FAKE_OUTPUTS),
        "inputs": list(FAKE_INPUTS),
        "blinksticks": list(FAKE_BLINKSTICKS),
    }


@pytest.fixture
def silence_dialogs(monkeypatch):
    """Neutralize blocking modal popups so a headless run never hangs.

    Two flavors block on a real event loop:

    * The static helpers (``QMessageBox.information``/``warning``/``question`` and
      ``QInputDialog.getText``) used by the missing-device notice, validation
      warnings, and the note-marker prompt.
    * Instance dialogs built and ``.exec()``-ed directly — notably the designer's
      "save before closing?" prompt in ``SmaccWindow.closeEvent``, which pytest-qt
      triggers when it closes the window at teardown. ``exec`` returns ``Discard``
      so that path tears down cleanly without writing a file; ``question`` returns
      ``No`` so the session window's close is declined (no preference writes).
    """
    box = QtWidgets.QMessageBox
    monkeypatch.setattr(box, "information", lambda *a, **k: box.StandardButton.Ok)
    monkeypatch.setattr(box, "warning", lambda *a, **k: box.StandardButton.Ok)
    monkeypatch.setattr(box, "critical", lambda *a, **k: box.StandardButton.Ok)
    monkeypatch.setattr(box, "question", lambda *a, **k: box.StandardButton.No)
    monkeypatch.setattr(box, "exec", lambda self: box.StandardButton.Discard)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *a, **k: ("", False))


@pytest.fixture
def design_session(tmp_path):
    """A study-designer session: no run folder, no hardware, no log file."""
    session = SmaccSession(tmp_path / "study", design=True)
    yield session
    session.close()


@pytest.fixture
def live_session(tmp_path, monkeypatch):
    """A recording session rooted at a temp data dir.

    The real ``init_lsl_stream`` opens a network marker outlet; stub it so window
    construction stays offline and deterministic. ``close()`` (teardown) detaches
    the run's log-file handler so Windows can remove the temp dir.
    """
    monkeypatch.setattr(
        SmaccSession,
        "init_lsl_stream",
        lambda self, *a, **k: setattr(self, "outlet", None),
    )
    session = SmaccSession(tmp_path / "data", design=False)
    yield session
    session.close()

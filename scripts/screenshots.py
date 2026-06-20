"""Regenerate the documentation screenshots under ``docs/assets/``.

The screenshots in the docs are a *build output*, not hand-captured: this script
constructs each SMACC window headless (Qt's ``offscreen`` platform), renders it to
a pixmap with ``QWidget.grab()``, and writes ``docs/assets/screenshot-<name>.png``.
Running it again after a UI change refreshes every shot in one step, which is the
whole point — screenshots rot the moment a label or layout moves, and a single
``uv run python scripts/screenshots.py`` is cheaper than re-snapping a dozen windows
by hand.

It borrows the test suite's stubs (see ``tests/conftest.py``): neutralize the only
construction-time hardware access (device enumeration, the Windows volume API, the
LSL marker outlet) and the close-time modal prompts, then build each window over a
throwaway :class:`~smacc.session.SmaccSession` seeded from the bundled
``default.smacc``. The app always opens light (the "lights off" dark theme is a
per-session toggle); the one dark shot drives that toggle on purpose to document the
night-mode feature.

    uv run python scripts/screenshots.py             # faithful shots (native platform)
    uv run python scripts/screenshots.py --headless  # CI smoke-run (offscreen)
"""

from __future__ import annotations

import os
import sys

# Render with the native platform by default: it supplies the system fonts and the
# dark-theme palette that the offscreen plugin lacks (offscreen renders text as tofu
# and can't honor the lights-off dark scheme), so native gives the faithful shots
# users actually see. The windows flash up briefly during a regen — fine for a manual
# dev command. ``--headless`` (or exporting QT_QPA_PLATFORM=offscreen) forces the
# offscreen plugin for a CI smoke-run that only checks every window still constructs.
# This must run before PyQt6 is imported anywhere.
if "--headless" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import tempfile
from pathlib import Path

from PyQt6 import QtCore, QtGui, QtWidgets

from smacc import devices, winvolume
from smacc.cuedesigner import CueDesignerWindow
from smacc.fonts import UI_FAMILY, apply_app_font
from smacc.gui import SmaccWindow
from smacc.launcher import LauncherWindow
from smacc.panels import devices as devices_panel
from smacc.panels.audio import AudioCueWindow
from smacc.panels.biocals import BiocalsWindow
from smacc.panels.chat import ChatWindow, ParticipantChatWindow
from smacc.panels.devices import DevicesWindow
from smacc.panels.recording import RecordingWindow
from smacc.panels.visual import VisualWindow
from smacc.panels.volume import VolumeWindow
from smacc.session import SmaccSession

ASSETS = Path(__file__).resolve().parent.parent / "docs" / "assets"
OUT_DIR = ASSETS  # where PNGs land; overridden by --out (the CI smoke uses a temp dir)

# Docs-friendly device names for the routing dropdowns. The default SMACC file binds
# no roles, so these only populate the combos (nothing resolves to "missing device").
DOC_OUTPUTS = ["Bedroom speakers", "Experimenter earbuds"]
DOC_INPUTS = ["Bedroom microphone"]
DOC_BLINKSTICKS = [("BlinkStick Square", "BS000001")]


def _patch_hardware() -> None:
    """Stub every bit of real hardware access a window touches at construction."""
    devices_panel.wasapi_devices = lambda kind: (
        list(DOC_INPUTS) if kind == devices.INPUT else list(DOC_OUTPUTS)
    )
    devices_panel.default_wasapi_device = lambda kind: (
        DOC_INPUTS[0] if kind == devices.INPUT else DOC_OUTPUTS[0]
    )
    devices_panel.blinkstick_devices = lambda: list(DOC_BLINKSTICKS)
    # The Volume window reads the live Windows endpoint/app mixer; show plausible
    # levels rather than the "unavailable" placeholders.
    winvolume.available = lambda: True
    winvolume.endpoint_volume = lambda: 0.6
    winvolume.app_volume = lambda: 1.0
    # The marker outlet would open a network stream in a live session.
    SmaccSession.init_lsl_stream = lambda self, *a, **k: setattr(self, "outlet", None)


# A clean, representative data directory for the Editor shot (the real one is a
# throwaway temp path that would leak a username and never reproduce).
DOC_DATA_DIR = r"C:\Users\you\Documents\SMACC\my-study"


def _bind_devices(session: SmaccSession) -> None:
    """Route the rig's equipment to the doc devices so windows show real bindings.

    A fresh SMACC file binds nothing, so every window otherwise reads "(not set)"
    and the Devices window is a wall of red "→ no device". Binding makes the shots
    look like a configured study (which is what the pages are documenting).
    """
    session.devices.bindings.update(
        {
            "bedroom_speaker": DOC_OUTPUTS[0],
            "control_speaker": DOC_OUTPUTS[1],
            "bedroom_mic_1": DOC_INPUTS[0],
            "control_mic": DOC_INPUTS[0],
            "blinkstick_light": DOC_BLINKSTICKS[0][1],
        }
    )


def _silence_dialogs() -> None:
    """Neutralize the modal prompts a window raises when it closes.

    Closing the Editor pops a "save before closing?" prompt and closing a live
    Session asks "end the session?"; both ``.exec()`` a modal dialog that blocks
    forever with no event loop. Mirror ``tests/conftest.py``'s ``silence_dialogs``.
    """
    box = QtWidgets.QMessageBox
    box.information = staticmethod(lambda *a, **k: box.StandardButton.Ok)
    box.warning = staticmethod(lambda *a, **k: box.StandardButton.Ok)
    box.critical = staticmethod(lambda *a, **k: box.StandardButton.Ok)
    box.question = staticmethod(lambda *a, **k: box.StandardButton.No)
    box.exec = lambda self: box.StandardButton.Discard
    QtWidgets.QInputDialog.getText = staticmethod(lambda *a, **k: ("", False))


def _load_ui_font(app: QtWidgets.QApplication) -> None:
    """Use SMACC's bundled B612 font, so the shots match the shipped app (#279).

    Registering the bundled family also cures the offscreen plugin's tofu: that
    plugin ships no font database, so without a registered font every label
    renders as □. Only if B612 somehow fails to register does this fall back to a
    system UI font, purely to keep headless shots legible.
    """
    apply_app_font(app)
    if UI_FAMILY in app.font().families():
        return
    for path in (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"):
        font_id = QtGui.QFontDatabase.addApplicationFont(path)
        if font_id == -1:
            continue
        families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QtGui.QFont(families[0], 9))
            return


def _make_app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # Mirror __main__: Fusion honors the full palette, and the docs want light shots.
    app.setStyle("Fusion")
    QtGui.QGuiApplication.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Light)
    _load_ui_font(app)
    return app


def _capture(app, widget, name, size=None):
    """Lay out a window offscreen and save its client area to a PNG."""
    if size is not None:
        widget.resize(*size)
    else:
        widget.adjustSize()
    widget.show()
    app.processEvents()
    app.processEvents()  # a second pass settles deferred layout/paint
    path = OUT_DIR / f"screenshot-{name}.png"
    widget.grab().save(str(path))
    print(f"  wrote {path.name}  ({widget.width()}x{widget.height()})")
    widget.close()
    app.processEvents()


def main(out_dir: Path = ASSETS) -> None:
    global OUT_DIR
    OUT_DIR = out_dir
    _patch_hardware()
    _silence_dialogs()
    app = _make_app()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        design = SmaccSession(root / "study", design=True)
        live = SmaccSession(root / "data", design=False)
        _bind_devices(design)

        print("Capturing light-theme windows:")
        _capture(app, LauncherWindow(), "launcher")
        _capture(app, SmaccWindow(live), "session", size=(1000, 680))

        editor = SmaccWindow(design)
        editor.dataDirLabel.setText(DOC_DATA_DIR)  # don't leak the temp path
        _capture(app, editor, "editor", size=(1000, 680))
        _capture(app, DevicesWindow(design), "devices")
        _capture(app, BiocalsWindow(design), "biocals")
        _capture(app, AudioCueWindow(design), "audio-cue")
        _capture(app, VisualWindow(design), "visual")
        _capture(app, ChatWindow(design), "intercom")
        _capture(app, ParticipantChatWindow(design), "chat")
        _capture(app, VolumeWindow(design), "volume")
        _capture(app, RecordingWindow(design), "recording")
        _capture(app, CueDesignerWindow(), "cue-designer")

        live.close()

        # The one dark shot: drive the lights-off toggle to document night mode. A
        # fresh session — the one above was closed by its window's "end session" path.
        print("Capturing the dark (lights-off) session:")
        night = SmaccSession(root / "night", design=False)
        dark = SmaccWindow(night)
        dark.set_lights(False)
        app.processEvents()
        _capture(app, dark, "session-dark", size=(1000, 680))
        QtGui.QGuiApplication.styleHints().setColorScheme(QtCore.Qt.ColorScheme.Light)

        design.close()
        night.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Regenerate the docs screenshots.")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Force Qt's offscreen platform (CI smoke; text/theme not faithful).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ASSETS,
        help=f"Directory to write the PNGs into (default: {ASSETS}).",
    )
    main(out_dir=parser.parse_args().out)

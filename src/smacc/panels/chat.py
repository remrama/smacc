"""The Chat feature: voice talk/listen, the typed channel, and both windows (#20, #92).

The experimenter's control-room **Chat** window (:class:`ChatWindow`) carries two
live voice bridges (Talk to the participant, Listen back) and, below them, the
experimenter's view of the typed channel. The participant's bedroom-facing window
(:class:`ParticipantChatWindow`) is the other end of that typed channel — for
hearing-impaired participants or whenever audio would intrude. Same-machine by
design: both views live in one SMACC process sharing one :class:`ChatTranscript`
and one :class:`ChatPresets`, so there is no network transport.

Two realities shape the typed channel:

* **One keyboard focus.** Windows gives the machine a single input focus, so the two
  keyboards (control room + bedroom) both type into whichever window is active. The
  exchange is half-duplex, like push-to-talk: the experimenter *passes* the keyboard
  explicitly (the Chat window's button, which activates the bedroom window), and that
  window says loudly whether the keyboard is "here" — a participant typing blind
  into an unfocused window would otherwise lose keystrokes silently. The bedroom has
  a keyboard but no mouse, so the entry holds focus whenever the window is active.
* **A dark bedroom.** The bedroom window keeps its own always-dark stylesheet,
  independent of the app theme (the lightswitch tracks the *control room's* lights):
  large text, a red-shifted night option, no flashing.

Messages are log-only by default: the verbatim text lands on a DEBUG line in the
session log (always in the file; out of the live preview and the BIDS export), and
the registry pair (``ChatMessageSent``/``ChatMessageReceived``) stays untriggered
unless a study flips it on — and even then the marker line stays bare, so the
trigger channel and the exported ``trial_type`` aren't flooded with conversation.
"""

from __future__ import annotations

import queue
import re
from functools import partial

import sounddevice as sd
from PyQt6 import QtCore, QtGui, QtWidgets

from .. import audio, config, devices
from ..dialogs import ManageChatPresetsDialog
from ..session import SmaccSession
from .base import (
    PanelWindow,
    describe_action,
    describe_equipment,
    make_section_title,
    require_device,
    require_equipment_device,
)
from .meter import LevelMeter

# Sender keys for transcript entries (and their registry/log identities below).
EXPERIMENTER = "experimenter"
PARTICIPANT = "participant"

_EVENT_KEYS = {EXPERIMENTER: "ChatMessageSent", PARTICIPANT: "ChatMessageReceived"}
_LOG_LABELS = {
    EXPERIMENTER: "Chat to participant",
    PARTICIPANT: "Chat from participant",
}

# Font bounds for the participant view (points). Wide on purpose: "large readable
# text" depends on monitor size and viewing distance, both rig-specific.
FONT_MIN = 8
FONT_MAX = 72
FONT_DEFAULT = 18

# Always-dark palettes for the bedroom-facing window. Neutral is dim gray-on-black;
# red shifts the text warm for labs that prefer red light at night. Both stay
# deliberately low-contrast — the window must never glow in a dark bedroom.
_NEUTRAL = {
    "fg": "#c8c8c8",
    "dim": "#7a7a7a",
    "bg": "#0e0e0e",
    "field": "#1a1a1a",
    "banner_bg": "#262626",
}
_RED = {
    "fg": "#cc7766",
    "dim": "#7e4a40",
    "bg": "#0e0a09",
    "field": "#1c1210",
    "banner_bg": "#2a1814",
}


def sanitize_message(text: str) -> str:
    """Collapse a typed message to one clean, log-safe line.

    The session log and the BIDS parser are line-based, so embedded newlines/tabs
    (e.g. pasted text) are collapsed to single spaces. A message *ending* in
    ``" - portcode N"`` would make an untriggered log line read as a marker to the
    BIDS parser, so that tail gets a period appended to neutralize it.
    """
    text = " ".join(text.split())
    if re.search(r" - portcode \d+$", text):
        text += "."
    return text


def _clean_presets(items: object) -> list[str]:
    """Coerce a saved/edited preset list to clean, non-empty, log-safe lines.

    Hand-edited studies must not crash a load, so a non-list (or non-string entry)
    is dropped rather than raised on; presets are sanitized like any message so a
    one-click send and a typed send produce identical log lines.
    """
    if not isinstance(items, list):
        return []
    cleaned = (sanitize_message(item) for item in items if isinstance(item, str))
    return [text for text in cleaned if text]


class ChatTranscript(QtCore.QObject):
    """The shared conversation: an ordered list of ``(sender, text)`` messages.

    One instance is shared by the experimenter view (the Chat window) and the
    participant window; both render from :attr:`message_posted`. Run data, not
    config — it is never persisted in a study (the session log is the record).
    """

    message_posted = QtCore.pyqtSignal(str, str)  # (sender key, sanitized text)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.messages: list[tuple[str, str]] = []

    def post(self, sender: str, text: str) -> None:
        """Append a message and notify both views."""
        self.messages.append((sender, text))
        self.message_posted.emit(sender, text)


class ChatPresets(QtCore.QObject):
    """Quick-reply presets (#112) shared by the two chat views.

    Two ordered lists: the experimenter's one-click prompts (the Chat window) and the
    participant's number-key replies (their window). Study-level *config* — edited
    from the Chat window and persisted in the ``.smacc`` (unlike
    :class:`ChatTranscript`, which is run data) — so one instance is shared, like the
    transcript, and both views rebuild from :attr:`changed`. The defaults seed a
    study that hasn't customized them; an explicitly empty list is respected on load.
    """

    changed = QtCore.pyqtSignal()

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.experimenter: list[str] = _clean_presets(config.CHAT_EXPERIMENTER_PRESETS)
        self.participant: list[str] = self._cap(
            _clean_presets(config.CHAT_PARTICIPANT_PRESETS)
        )

    @staticmethod
    def _cap(items: list[str]) -> list[str]:
        """Participant replies past the ninth have no number key, so drop them."""
        return items[: config.MAX_PARTICIPANT_PRESETS]

    def set(self, experimenter: list[str], participant: list[str]) -> None:
        """Replace both lists (e.g. from the manage dialog) and notify both views."""
        self.experimenter = _clean_presets(experimenter)
        self.participant = self._cap(_clean_presets(participant))
        self.changed.emit()

    def gather_state(self) -> dict:
        return {
            "chat_experimenter_presets": list(self.experimenter),
            "chat_participant_presets": list(self.participant),
        }

    def apply_state(self, state: dict) -> None:
        """Load saved presets; an absent key keeps the seeded defaults.

        Mirrors the biocals stack: a missing key falls back to the shipped defaults,
        while a present list (even empty) is honoured as a deliberate choice.
        """
        present = False
        if "chat_experimenter_presets" in state:
            self.experimenter = _clean_presets(state["chat_experimenter_presets"])
            present = True
        if "chat_participant_presets" in state:
            self.participant = self._cap(
                _clean_presets(state["chat_participant_presets"])
            )
            present = True
        if present:
            self.changed.emit()


def post_chat_message(
    session: SmaccSession, transcript: ChatTranscript, sender: str, text: str
) -> str | None:
    """Sanitize, record, and log one chat message; return it (None if empty).

    The verbatim text always goes to a DEBUG log line — in the session file for the
    record, out of the live preview and the BIDS export by default. The registry
    event fires only when a study has routed it to a transport (LSL/TTL), and then
    *bare* (no message text), so the marker channel stays legible however chatty
    the exchange.
    """
    clean = sanitize_message(text)
    if not clean:
        return None
    transcript.post(sender, clean)
    event = session.events.get(_EVENT_KEYS[sender])
    if event is not None and event.triggered:
        session.emit_event(event.key)
    label = event.label if event is not None else _LOG_LABELS[sender]
    session.log_debug_msg(f"{label}: {clean}")
    return clean


def _stylesheet(pal: dict[str, str]) -> str:
    """The participant window's fixed dark stylesheet for one palette."""
    return (
        f"QMainWindow, QWidget {{ background-color: {pal['bg']}; color: {pal['fg']}; }}"
        f"QPlainTextEdit {{ background-color: {pal['bg']}; color: {pal['fg']};"
        f" border: none; }}"
        f"QLineEdit {{ background-color: {pal['field']}; color: {pal['fg']};"
        f" border: 1px solid {pal['dim']}; border-radius: 4px; padding: 6px; }}"
        # Reply chips: dim, padded, left-aligned — readable from bed, never glaring.
        f"QPushButton {{ background-color: {pal['field']}; color: {pal['fg']};"
        f" border: 1px solid {pal['dim']}; border-radius: 6px; padding: 10px;"
        f" text-align: left; }}"
        f"QMenuBar {{ background-color: {pal['bg']}; color: {pal['dim']}; }}"
        f"QMenuBar::item:selected {{ background-color: {pal['field']}; }}"
        f"QMenu {{ background-color: {pal['field']}; color: {pal['fg']}; }}"
    )


class ParticipantChatWindow(PanelWindow):
    """The bedroom-facing chat window: always dark, big text, keyboard-only.

    Opened (and given keyboard focus) from the Chat window's *Pass keyboard*
    button; the operator drags it onto the bedroom display once, and its geometry
    persists machine-locally like every tool window, so it reopens there. Closing
    hides it (the conversation survives in the shared transcript).
    """

    TITLE = "Participant chat"

    def __init__(
        self,
        session: SmaccSession,
        transcript: ChatTranscript | None = None,
        presets: ChatPresets | None = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(session, parent)
        self._transcript = (
            transcript if transcript is not None else ChatTranscript(self)
        )
        self._presets = presets if presets is not None else ChatPresets(self)
        self._font_size = FONT_DEFAULT
        self.setCentralWidget(self._build())
        self._build_display_menu()
        self._transcript.message_posted.connect(self._append_message)
        self._presets.changed.connect(self._on_presets_changed)
        self._rebuild_presets()
        self._apply_font()
        self._apply_theme()
        self.resize(560, 420)

    def _build(self) -> QtWidgets.QWidget:
        # The banner is the participant's only feedback about where the machine's
        # single keyboard focus is — it must be readable from bed, half asleep.
        self.keyboardBanner = QtWidgets.QLabel(self)
        self.keyboardBanner.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.keyboardBanner.setWordWrap(True)

        view = QtWidgets.QPlainTextEdit(self)
        view.setReadOnly(True)
        # Not focusable: the entry below must keep focus — the participant has a
        # keyboard but no mouse, so stranded focus can't be clicked back.
        view.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.view = view

        # Quick-reply chips (#112): numbered replies sent with the number keys 1-9.
        # Non-focusable for the same reason as the view — the entry keeps focus.
        self._preset_buttons: list[QtWidgets.QPushButton] = []
        self.presetContainer = QtWidgets.QWidget(self)
        self.presetLayout = QtWidgets.QVBoxLayout(self.presetContainer)
        self.presetLayout.setContentsMargins(0, 0, 0, 0)

        entry = QtWidgets.QLineEdit(self)
        entry.setPlaceholderText("Type here, then press Enter to send")
        entry.returnPressed.connect(self._send)
        # A bare number key (1-9) sends the matching quick reply, but only while the
        # entry is empty, so a typed reply containing digits still works (see
        # eventFilter).
        entry.installEventFilter(self)
        self.entry = entry

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.keyboardBanner)
        layout.addWidget(view, 1)
        layout.addWidget(self.presetContainer)
        layout.addWidget(entry)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def _build_display_menu(self) -> None:
        """Add the Display menu: red night text and the text-size actions."""
        menu_bar = self.menuBar()
        assert menu_bar is not None
        menu = menu_bar.addMenu("&Display")
        assert menu is not None
        red = QtGui.QAction("&Red night text", self)
        red.setCheckable(True)
        red.toggled.connect(self._on_red_toggled)
        self._red_action = red
        bigger = QtGui.QAction("&Increase text size", self)
        bigger.setShortcuts(
            [QtGui.QKeySequence("Ctrl+="), QtGui.QKeySequence("Ctrl++")]
        )
        bigger.triggered.connect(lambda: self._step_font(+2))
        smaller = QtGui.QAction("&Decrease text size", self)
        smaller.setShortcut(QtGui.QKeySequence("Ctrl+-"))
        smaller.triggered.connect(lambda: self._step_font(-2))
        for action in (red, bigger, smaller):
            menu.addAction(action)

    # ----- appearance ---------------------------------------------------------

    def _palette_colors(self) -> dict[str, str]:
        return _RED if self._red_action.isChecked() else _NEUTRAL

    def _apply_theme(self) -> None:
        """Apply the always-dark stylesheet (independent of the app-wide theme)."""
        self.setStyleSheet(_stylesheet(self._palette_colors()))
        self._refresh_keyboard_banner()

    def _on_red_toggled(self, enabled: bool) -> None:
        self._apply_theme()
        self.session.log_interaction(
            f"Chat red night text {'enabled' if enabled else 'disabled'}"
        )

    def _apply_font(self) -> None:
        font = QtGui.QFont()
        font.setPointSize(self._font_size)
        for widget in (
            self.view,
            self.entry,
            self.keyboardBanner,
            *self._preset_buttons,
        ):
            widget.setFont(font)

    def _step_font(self, delta: int) -> None:
        self._font_size = max(FONT_MIN, min(FONT_MAX, self._font_size + delta))
        self._apply_font()
        self.session.log_interaction(f"Chat text size {self._font_size}pt", debug=True)

    def _refresh_keyboard_banner(self) -> None:
        """Show, unmissably, whether keystrokes will land in this window."""
        pal = self._palette_colors()
        if self.isActiveWindow():
            self.keyboardBanner.setText("● The keyboard is yours — type below")
            style = (
                f"background-color: {pal['banner_bg']}; color: {pal['fg']};"
                " padding: 8px; border-radius: 6px;"
            )
        else:
            self.keyboardBanner.setText("○ Waiting — the keyboard is not here")
            style = (
                f"background-color: transparent; color: {pal['dim']};"
                " padding: 8px; border-radius: 6px;"
            )
        self.keyboardBanner.setStyleSheet(style)

    # ----- conversation -------------------------------------------------------

    def _append_message(self, sender: str, text: str) -> None:
        name = "You" if sender == PARTICIPANT else "Experimenter"
        self.view.appendPlainText(f"{name}:  {text}")
        scrollbar = self.view.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    def _send(self) -> None:
        self._send_text(self.entry.text())

    def _send_text(self, text: str) -> None:
        """Post ``text`` as the participant — a typed entry or a quick reply."""
        posted = post_chat_message(self.session, self._transcript, PARTICIPANT, text)
        if posted is not None:
            self.entry.clear()

    # ----- quick replies ------------------------------------------------------

    def _rebuild_presets(self) -> None:
        """Rebuild the numbered reply chips from the shared presets."""
        for button in self._preset_buttons:
            button.deleteLater()
        self._preset_buttons = []
        for number, text in enumerate(self._presets.participant, start=1):
            button = QtWidgets.QPushButton(f"{number}.  {text}", self.presetContainer)
            # No mouse in the bedroom, so the number key is the real trigger; the chip
            # stays clickable (harmless, ready for a future touch display) but never
            # takes focus away from the entry.
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            button.clicked.connect(partial(self._send_text, text))
            self.presetLayout.addWidget(button)
            self._preset_buttons.append(button)
        self.presetContainer.setVisible(bool(self._preset_buttons))

    def _on_presets_changed(self) -> None:
        self._rebuild_presets()
        self._apply_font()

    # ----- window behaviour ---------------------------------------------------

    def changeEvent(self, event) -> None:
        if event is not None and event.type() == QtCore.QEvent.Type.ActivationChange:
            self._refresh_keyboard_banner()
        super().changeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.entry.setFocus()
        self._refresh_keyboard_banner()

    def eventFilter(self, obj, event) -> bool:
        """Send a quick reply when a number key is pressed on an empty entry.

        The participant types into ``self.entry``; a bare ``1``-``9`` there fires the
        matching chip, but only while nothing is typed, so a free-text reply that
        contains digits is left alone. The keystroke is consumed so the digit isn't
        also inserted.
        """
        if (
            obj is self.entry
            and event is not None
            and event.type() == QtCore.QEvent.Type.KeyPress
            and not self.entry.text()
        ):
            index = event.key() - QtCore.Qt.Key.Key_1
            if 0 <= index < len(self._presets.participant):
                self._send_text(self._presets.participant[index])
                return True
        return super().eventFilter(obj, event)

    # ----- persisted state ----------------------------------------------------

    def gather_state(self) -> dict:
        return {
            "chat_font_size": self._font_size,
            "chat_red_text": self._red_action.isChecked(),
        }

    def apply_state(self, state: dict) -> None:
        try:
            self._font_size = max(FONT_MIN, min(FONT_MAX, int(state["chat_font_size"])))
        except (KeyError, TypeError, ValueError):
            pass  # keep the current size; hand-edited studies must not crash a load
        self._apply_font()
        red = bool(state.get("chat_red_text", False))
        self._red_action.blockSignals(True)
        self._red_action.setChecked(red)
        self._red_action.blockSignals(False)
        self._apply_theme()


# Cap an experimenter prompt's button label so a long standardized question doesn't
# stretch the panel; the full text rides along in the tooltip/status tip.
_PRESET_LABEL_LIMIT = 48


def _elide(text: str, limit: int = _PRESET_LABEL_LIMIT) -> str:
    """Shorten ``text`` to ``limit`` chars with an ellipsis (full text in a tooltip)."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class _Bridge:
    """A one-direction live audio bridge: an input device piped to an output device.

    The input and output run as separate streams at their own native rates, bridged
    by a queue + linear resampler. On overrun a block is dropped rather than blocking
    the audio thread.
    """

    def __init__(self) -> None:
        self._input: sd.InputStream | None = None
        self._output: sd.OutputStream | None = None
        self._queue: queue.Queue | None = None
        self._resampler: audio.LinearResampler | None = None
        # Latest input level (dBFS), stashed by the audio callback for the
        # window's level meters (a plain float store; the GUI timer reads it).
        self.level_db = audio.FLOOR_DBFS

    def active(self) -> bool:
        """True while either stream is open."""
        return self._input is not None or self._output is not None

    def start(
        self, input_device: int | str | None, output_device: int | str | None
    ) -> None:
        """Open and start the streams; raises (and tears down) on a PortAudio error."""
        try:
            in_rate = int(sd.query_devices(input_device, "input")["default_samplerate"])
            out_rate = int(
                sd.query_devices(output_device, "output")["default_samplerate"]
            )
            self._queue = queue.Queue(maxsize=32)
            self._resampler = audio.LinearResampler(in_rate, out_rate)
            self._input = sd.InputStream(
                samplerate=in_rate,
                channels=1,
                device=input_device,
                callback=self._in_callback,
            )
            self._output = sd.OutputStream(
                samplerate=out_rate,
                channels=1,
                device=output_device,
                callback=self._out_callback,
            )
            self._input.start()
            self._output.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> bool:
        """Tear down both streams; return True if either was running."""
        stopped = False
        for stream in (self._input, self._output):
            if stream is not None:
                stream.abort()
                stream.close()
                stopped = True
        self._input = None
        self._output = None
        self._queue = None
        self._resampler = None
        self.level_db = audio.FLOOR_DBFS
        return stopped

    def _in_callback(self, indata, frames, time, status) -> None:
        self.level_db = audio.rms_dbfs(indata)
        if self._queue is not None:
            try:
                self._queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass  # output not keeping up; drop a block rather than block

    def _out_callback(self, outdata, frames, time, status) -> None:
        if self._queue is not None and self._resampler is not None:
            while True:
                try:
                    self._resampler.push(self._queue.get_nowait())
                except queue.Empty:
                    break
            outdata[:, 0] = self._resampler.pull(frames)
        else:
            outdata.fill(0)


class ChatWindow(PanelWindow):
    """Talk to the participant (push-to-talk) and listen back, in either direction."""

    TITLE = "Chat"

    # Asks the main window to show + activate the participant chat window. Routed
    # there because activating it is also how the machine's single keyboard focus
    # is handed to the participant (see :class:`ParticipantChatWindow`).
    open_participant_chat = QtCore.pyqtSignal()

    def __init__(
        self,
        session: SmaccSession,
        transcript: ChatTranscript | None = None,
        presets: ChatPresets | None = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(session, parent)
        self._talk = _Bridge()  # experimenter mic -> participant output
        self._listen = _Bridge()  # participant mic -> control-room output
        self._talk_push = False  # True while talk is held via the spacebar
        # Renders each live bridge's input level onto its meter; runs only while
        # a direction is on (started/stopped by the toggles).
        self._level_timer = QtCore.QTimer(self)
        self._level_timer.setInterval(50)  # ~20 Hz display refresh
        self._level_timer.timeout.connect(self._render_levels)
        self._transcript = (
            transcript if transcript is not None else ChatTranscript(self)
        )
        self._presets = presets if presets is not None else ChatPresets(self)
        self.setCentralWidget(self._build())
        self._transcript.message_posted.connect(self._append_chat_message)
        self._presets.changed.connect(self._rebuild_preset_buttons)
        self._rebuild_preset_buttons()
        # App-wide spacebar push-to-talk works regardless of the focused window.
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _build(self) -> QtWidgets.QWidget:
        # Devices are chosen in the Devices window; show where each direction routes.
        self.talkDeviceLabel = QtWidgets.QLabel(self)
        self.listenDeviceLabel = QtWidgets.QLabel(self)
        self.refresh_device_indicator()

        talkButton = QtWidgets.QPushButton("Talk (to participant)", self)
        talkButton.setStatusTip(
            "Click to latch on/off, or press and hold the spacebar to talk "
            "(push-to-talk). Warning: risks feedback near open speakers."
        )
        talkButton.setCheckable(True)
        talkButton.toggled.connect(self.toggle_talk)
        self.talkButton = talkButton

        listenButton = QtWidgets.QPushButton("Listen (to participant)", self)
        listenButton.setStatusTip(
            "Hear the participant's mic on the control-room output (set the route in "
            "the Devices window)."
        )
        listenButton.setCheckable(True)
        listenButton.toggled.connect(self.toggle_listen)
        self.listenButton = listenButton

        # A level meter beside each direction, fed from that bridge's live input
        # callback — signal on the bar means audio is actually flowing (your mic
        # for Talk, the participant's mic for Listen), not just a latched button.
        self.talkMeter = LevelMeter(self)
        self.talkMeter.setStatusTip("Your mic's live level while Talk is on.")
        self.listenMeter = LevelMeter(self)
        self.listenMeter.setStatusTip(
            "The participant mic's live level while Listen is on."
        )
        talkRow = QtWidgets.QHBoxLayout()
        talkRow.addWidget(talkButton, 1)
        talkRow.addWidget(self.talkMeter, 1)
        listenRow = QtWidgets.QHBoxLayout()
        listenRow.addWidget(listenButton, 1)
        listenRow.addWidget(self.listenMeter, 1)

        # --- Text chat (#92): the experimenter's view of the typed channel -----
        chatView = QtWidgets.QPlainTextEdit(self)
        chatView.setReadOnly(True)
        chatView.setMinimumHeight(120)
        chatView.setStatusTip(
            "The typed conversation (always recorded in the session log)."
        )
        self.chatView = chatView

        chatEntry = QtWidgets.QLineEdit(self)
        chatEntry.setPlaceholderText("Type to the participant…")
        chatEntry.setStatusTip(
            "Enter sends; Ctrl+Enter sends and passes the keyboard to the participant."
        )
        chatEntry.returnPressed.connect(self.send_chat_message)
        self.chatEntry = chatEntry
        # Ctrl+Enter = send-and-pass, only while the entry itself has focus.
        sendAndPass = QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Return"), chatEntry)
        sendAndPass.setContext(QtCore.Qt.ShortcutContext.WidgetShortcut)
        sendAndPass.activated.connect(self.send_and_pass_keyboard)

        sendButton = QtWidgets.QPushButton("Send", self)
        sendButton.setStatusTip("Show the typed message to the participant.")
        sendButton.clicked.connect(self.send_chat_message)
        entryRow = QtWidgets.QHBoxLayout()
        entryRow.addWidget(chatEntry, 1)
        entryRow.addWidget(sendButton)

        passButton = QtWidgets.QPushButton("Pass keyboard to participant", self)
        passButton.setStatusTip(
            "Show the participant chat window and give it keyboard focus — the "
            "machine has one focus, so only one side can type at a time."
        )
        passButton.clicked.connect(self.open_participant_chat.emit)

        # Quick messages (#112): one-click standardized prompts, sent verbatim through
        # the same path as a typed message. Rebuilt from the shared presets.
        self._presetContainer = QtWidgets.QWidget(self)
        self._presetLayout = QtWidgets.QVBoxLayout(self._presetContainer)
        self._presetLayout.setContentsMargins(0, 0, 0, 0)
        self._preset_buttons: list[QtWidgets.QPushButton] = []

        manageButton = QtWidgets.QPushButton("Manage quick messages…", self)
        manageButton.setStatusTip(
            "Add, edit, or reorder the experimenter prompts and the participant's "
            "number-key replies (saved with the study)."
        )
        manageButton.clicked.connect(self.manage_presets)

        layout = QtWidgets.QFormLayout()
        layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addRow(make_section_title("Voice"))
        layout.addRow("To participant:", self.talkDeviceLabel)
        layout.addRow(talkRow)
        layout.addRow("From participant:", self.listenDeviceLabel)
        layout.addRow(listenRow)
        layout.addRow(make_section_title("Text chat"))
        layout.addRow(chatView)
        layout.addRow(self._presetContainer)
        layout.addRow(entryRow)
        layout.addRow(passButton)
        layout.addRow(manageButton)
        central = QtWidgets.QWidget()
        central.setLayout(layout)
        return central

    def send_chat_message(self) -> None:
        """Post the typed entry to the shared transcript (logged; marker if enabled)."""
        posted = post_chat_message(
            self.session, self._transcript, EXPERIMENTER, self.chatEntry.text()
        )
        if posted is not None:
            self.chatEntry.clear()

    def send_and_pass_keyboard(self) -> None:
        """Send the entry (if any), then hand the keyboard to the participant."""
        self.send_chat_message()
        self.open_participant_chat.emit()

    def _append_chat_message(self, sender: str, text: str) -> None:
        name = "You" if sender == EXPERIMENTER else "Participant"
        self.chatView.appendPlainText(f"{name}:  {text}")
        scrollbar = self.chatView.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.setValue(scrollbar.maximum())

    # ----- quick messages (#112) ----------------------------------------------

    def _rebuild_preset_buttons(self) -> None:
        """Rebuild the one-click prompt buttons from the shared presets."""
        for button in self._preset_buttons:
            button.deleteLater()
        self._preset_buttons = []
        for text in self._presets.experimenter:
            button = QtWidgets.QPushButton(_elide(text), self._presetContainer)
            button.setToolTip(text)
            button.setStatusTip(f"Send to the participant: {text}")
            button.clicked.connect(partial(self._send_preset, text))
            self._presetLayout.addWidget(button)
            self._preset_buttons.append(button)
        self._presetContainer.setVisible(bool(self._preset_buttons))

    def _send_preset(self, text: str) -> None:
        """Send a standardized prompt through the same path as a typed message."""
        post_chat_message(self.session, self._transcript, EXPERIMENTER, text)

    def manage_presets(self) -> None:
        """Edit both preset lists; on accept, update the shared presets in place."""
        dialog = ManageChatPresetsDialog(
            self._presets.experimenter, self._presets.participant, parent=self
        )
        if dialog.exec():
            experimenter, participant = dialog.get_presets()
            self._presets.set(experimenter, participant)  # -> both views rebuild
            self.session.log_interaction("Edited chat quick-reply presets")

    def refresh_device_indicator(self) -> None:
        """Show both halves of each direction (devices set in the Devices window).

        Talk and Listen are mic → output paths, so each indicator shows the
        output route plus the source mic ("• mic: …"), the same separator idiom
        the Audio cue window uses for its monitor.
        """
        talk = describe_action(self.session, "speak_to_participant")
        talk += f"   •   mic: {describe_equipment(self.session, devices.TALK_SOURCE)}"
        self.talkDeviceLabel.setText(talk)
        listen = describe_action(self.session, "listen_to_participant")
        listen += (
            f"   •   mic: {describe_equipment(self.session, devices.LISTEN_SOURCE)}"
        )
        self.listenDeviceLabel.setText(listen)

    def is_streaming(self) -> bool:
        """True while either direction is live."""
        return self._talk.active() or self._listen.active()

    def _sync_level_timer(self) -> None:
        """Run the meter refresh only while a direction is live; clear idle bars."""
        if self.is_streaming():
            if not self._level_timer.isActive():
                self._level_timer.start()
        else:
            self._level_timer.stop()
        self._render_levels()

    def _render_levels(self) -> None:
        """GUI-thread timer: render each live bridge's input level onto its meter."""
        for bridge, meter in (
            (self._talk, self.talkMeter),
            (self._listen, self.listenMeter),
        ):
            if bridge.active():
                meter.show_level(bridge.level_db)
            else:
                meter.clear_level()

    def toggle_talk(self, enabled: bool) -> None:
        """Start/stop piping the experimenter mic to the participant output.

        Marked in the EEG record via LSL (the experimenter's voice is a manipulation
        the participant hears). The mic is the Control-room mic equipment (#160),
        the output the ``speak_to_participant`` route — both pinned by name,
        like every other audio path.
        """
        if enabled:
            mic = require_equipment_device(
                self.session,
                devices.TALK_SOURCE,
                devices.INPUT,
                failure="Could not start Talk.",
                parent=self,
            )
            if mic is None:
                self.talkButton.setChecked(False)
                return
            output = require_device(
                self.session,
                "speak_to_participant",
                devices.OUTPUT,
                failure="Could not start Talk.",
                parent=self,
            )
            if output is None:
                self.talkButton.setChecked(False)
                return
            try:
                self._talk.start(mic, output)
            except Exception as exc:  # PortAudio errors, no device, busy, etc.
                self.session.show_error_popup(
                    "Could not start Talk.", str(exc), parent=self
                )
                self.talkButton.setChecked(False)
                return
            self.session.emit_event("TalkStarted")
        elif self._talk.stop():
            self.session.emit_event("TalkStopped")
        self._sync_level_timer()

    def toggle_listen(self, enabled: bool) -> None:
        """Start/stop piping the participant mic to the control-room output.

        Passive monitoring (no EEG marker), the reverse of Talk: the bedroom mic is
        the source, the ``listen_to_participant`` route the destination.
        """
        if enabled:
            mic = require_equipment_device(
                self.session,
                devices.LISTEN_SOURCE,
                devices.INPUT,
                failure="Could not start Listen.",
                parent=self,
            )
            if mic is None:
                self.listenButton.setChecked(False)
                return
            output = require_device(
                self.session,
                "listen_to_participant",
                devices.OUTPUT,
                failure="Could not start Listen.",
                parent=self,
            )
            if output is None:
                self.listenButton.setChecked(False)
                return
            try:
                self._listen.start(mic, output)
            except Exception as exc:  # PortAudio errors, no device, busy, etc.
                self.session.show_error_popup(
                    "Could not start Listen.", str(exc), parent=self
                )
                self.listenButton.setChecked(False)
                return
            self.session.log_interaction("Voice listen on")
        else:
            self._listen.stop()
            self.session.log_interaction("Voice listen off")
        self._sync_level_timer()

    @staticmethod
    def _is_text_widget_focused() -> bool:
        """True if a text-entry widget has focus (so space should type, not talk)."""
        widget = QtWidgets.QApplication.focusWidget()
        return isinstance(
            widget,
            (
                QtWidgets.QLineEdit,
                QtWidgets.QAbstractSpinBox,
                QtWidgets.QTextEdit,
                QtWidgets.QPlainTextEdit,
            ),
        )

    def eventFilter(self, obj, event) -> bool:
        """Application-wide spacebar push-to-talk for the Talk direction.

        Installed on the QApplication so it sees the spacebar regardless of which
        widget/window has focus. Hold space to talk, release to stop; auto-repeat
        is swallowed so Talk never rapidly toggles. Space passes through untouched
        while a text-entry widget is focused, so typing still works.
        """
        etype = event.type()
        if (
            etype in (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.KeyRelease)
            and event.key() == QtCore.Qt.Key.Key_Space
            and not self._is_text_widget_focused()
        ):
            if etype == QtCore.QEvent.Type.KeyPress:
                if not event.isAutoRepeat() and not self.talkButton.isChecked():
                    self._talk_push = True
                    self.talkButton.setChecked(True)  # -> toggle_talk(True)
            elif not event.isAutoRepeat() and self._talk_push:
                self._talk_push = False
                self.talkButton.setChecked(False)  # -> toggle_talk(False)
            return True  # consume so the focused widget doesn't also see space
        return super().eventFilter(obj, event)

    # ----- persisted state ----------------------------------------------------

    def gather_state(self) -> dict:
        """Persist the quick-reply presets (the shared object's view)."""
        return self._presets.gather_state()

    def apply_state(self, state: dict) -> None:
        """Load the quick-reply presets; both chat views rebuild via the signal."""
        self._presets.apply_state(state)

    def cleanup(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self._level_timer.stop()
        self._talk.stop()
        self._listen.stop()

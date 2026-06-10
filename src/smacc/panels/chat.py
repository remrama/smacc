"""Participant-facing text chat: the shared transcript and the bedroom window (#92).

The intercom's typed channel, for hearing-impaired participants or whenever audio
would intrude: the experimenter types in the Intercom panel, the participant reads
and replies in this window, dragged once onto a bedroom-facing display. Same-machine
by design — both views live in one SMACC process sharing one :class:`ChatTranscript`,
so there is no network transport.

Two realities shape the design:

* **One keyboard focus.** Windows gives the machine a single input focus, so the two
  keyboards (control room + bedroom) both type into whichever window is active. The
  exchange is half-duplex, like push-to-talk: the experimenter *passes* the keyboard
  explicitly (the Intercom panel's button, which activates this window), and this
  window says loudly whether the keyboard is "here" — a participant typing blind
  into an unfocused window would otherwise lose keystrokes silently. The bedroom has
  a keyboard but no mouse, so the entry holds focus whenever the window is active.
* **A dark bedroom.** The window keeps its own always-dark stylesheet, independent
  of the app theme (the lightswitch tracks the *control room's* lights): large text,
  a red-shifted night option, no flashing.

Messages are log-only by default: the verbatim text lands on a DEBUG line in the
session log (always in the file; out of the live preview and the BIDS export), and
the registry pair (``ChatMessageSent``/``ChatMessageReceived``) stays untriggered
unless a study flips it on — and even then the marker line stays bare, so the
trigger channel and the exported ``trial_type`` aren't flooded with conversation.
"""

from __future__ import annotations

import re

from PyQt6 import QtCore, QtGui, QtWidgets

from ..session import SmaccSession
from .base import ModalityWindow

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


class ChatTranscript(QtCore.QObject):
    """The shared conversation: an ordered list of ``(sender, text)`` messages.

    One instance is shared by the experimenter view (in the Intercom panel) and the
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


def post_chat_message(
    session: SmaccSession, transcript: ChatTranscript, sender: str, text: str
) -> str | None:
    """Sanitize, record, and log one chat message; return it (None if empty).

    The verbatim text always goes to a DEBUG log line — in the session file for the
    record, out of the live preview and the BIDS export by default. The registry
    event fires only when a study has flipped its trigger on, and then *bare* (no
    message text), so the marker channel stays legible however chatty the exchange.
    """
    clean = sanitize_message(text)
    if not clean:
        return None
    transcript.post(sender, clean)
    event = session.events.get(_EVENT_KEYS[sender])
    if event is not None and event.trigger:
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
        f"QMenuBar {{ background-color: {pal['bg']}; color: {pal['dim']}; }}"
        f"QMenuBar::item:selected {{ background-color: {pal['field']}; }}"
        f"QMenu {{ background-color: {pal['field']}; color: {pal['fg']}; }}"
    )


class ParticipantChatWindow(ModalityWindow):
    """The bedroom-facing chat window: always dark, big text, keyboard-only.

    Opened (and given keyboard focus) from the Intercom panel's *Pass keyboard*
    button; the operator drags it onto the bedroom display once, and its geometry
    persists machine-locally like every tool window, so it reopens there. Closing
    hides it (the conversation survives in the shared transcript).
    """

    TITLE = "Participant chat"

    def __init__(
        self,
        session: SmaccSession,
        transcript: ChatTranscript | None = None,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(session, parent)
        self._transcript = (
            transcript if transcript is not None else ChatTranscript(self)
        )
        self._font_size = FONT_DEFAULT
        self.setCentralWidget(self._build())
        self._build_display_menu()
        self._transcript.message_posted.connect(self._append_message)
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

        entry = QtWidgets.QLineEdit(self)
        entry.setPlaceholderText("Type here, then press Enter to send")
        entry.returnPressed.connect(self._send)
        self.entry = entry

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.keyboardBanner)
        layout.addWidget(view, 1)
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
        for widget in (self.view, self.entry, self.keyboardBanner):
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
        posted = post_chat_message(
            self.session, self._transcript, PARTICIPANT, self.entry.text()
        )
        if posted is not None:
            self.entry.clear()

    # ----- window behaviour ---------------------------------------------------

    def changeEvent(self, event) -> None:
        if event is not None and event.type() == QtCore.QEvent.Type.ActivationChange:
            self._refresh_keyboard_banner()
        super().changeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.entry.setFocus()
        self._refresh_keyboard_banner()

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

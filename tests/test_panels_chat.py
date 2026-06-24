"""Tests for the text chat (#92): transcript, logging contract, and both views.

The logging contract is the heart: messages are log-only by default (verbatim text
on a DEBUG line, nothing in the BIDS export), and a study that flips a chat
trigger on gets a *bare* marker line — the message text never rides into the
trigger channel or ``trial_type``.
"""

from __future__ import annotations

import logging
from dataclasses import replace

from PyQt6 import QtCore

from smacc import bids, config, winvolume
from smacc.gui import SmaccWindow
from smacc.panels.chat import (
    EXPERIMENTER,
    FONT_DEFAULT,
    FONT_MAX,
    PARTICIPANT,
    ChatPresets,
    ChatTranscript,
    ChatWindow,
    ParticipantChatWindow,
    _clean_presets,
    post_chat_message,
    sanitize_message,
)


def _capture_session_log(session) -> list[logging.LogRecord]:
    """Attach a recording handler to a session's logger and return its record list.

    The session logger sets ``propagate=False`` (and design mode only has a
    NullHandler), so pytest's ``caplog`` never sees these records; capture on the
    logger directly instead.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    session.logger.addHandler(_Capture())
    return records


# ----- sanitization -----------------------------------------------------------


def test_sanitize_collapses_to_one_log_safe_line():
    assert sanitize_message("  hello\nthere\tworld  ") == "hello there world"
    assert sanitize_message("   \n\t ") == ""


def test_sanitize_neutralizes_a_marker_lookalike_tail():
    # A message *ending* in " - portcode N" on an untriggered (DEBUG) line would
    # read as a marker to the BIDS parser; the appended period defuses it.
    sanitized = sanitize_message("ok done - portcode 7")
    assert sanitized == "ok done - portcode 7."
    line = f"2026-06-09 23:00:00.000, DEBUG, Chat from participant: {sanitized}"
    assert bids.log_to_events(line) == []


# ----- the logging contract ---------------------------------------------------


def test_chat_message_is_a_debug_line_and_no_marker_by_default(headless_session):
    records = _capture_session_log(headless_session)
    transcript = ChatTranscript()
    posted = post_chat_message(
        headless_session, transcript, EXPERIMENTER, "  hello\nthere  "
    )
    assert posted == "hello there"
    assert transcript.messages == [(EXPERIMENTER, "hello there")]
    messages = [r.getMessage() for r in records]
    assert "Chat to participant: hello there" in messages
    assert all(r.levelno == logging.DEBUG for r in records)
    assert not any("portcode" in m for m in messages)  # log-only by default


def test_empty_message_posts_nothing(headless_session):
    records = _capture_session_log(headless_session)
    transcript = ChatTranscript()
    assert post_chat_message(headless_session, transcript, PARTICIPANT, "  \n ") is None
    assert transcript.messages == []
    assert records == []


def test_flipped_on_trigger_fires_a_bare_marker(live_session):
    # A study that wants marker timestamps routes the event to a transport in the
    # Event codes dialog; the marker line stays bare so trial_type/trigger channel
    # stay legible.
    live_session.events["ChatMessageSent"] = replace(
        live_session.events["ChatMessageSent"], lsl=True
    )
    transcript = ChatTranscript()
    post_chat_message(live_session, transcript, EXPERIMENTER, "Are you comfortable?")
    post_chat_message(live_session, transcript, PARTICIPANT, "yes")  # still log-only
    log_text = live_session.log_path.read_text(encoding="utf-8")
    rows = bids.log_to_events(log_text)
    assert [(r["trial_type"], r["value"]) for r in rows] == [
        ("Chat to participant", 69)
    ]
    # The verbatim exchange is still in the log file, on DEBUG lines.
    assert "Chat to participant: Are you comfortable?" in log_text
    assert "Chat from participant: yes" in log_text


# ----- participant window -----------------------------------------------------


def test_participant_window_defaults_and_state_round_trip(qtbot, headless_session):
    window = ParticipantChatWindow(headless_session)
    qtbot.addWidget(window)
    assert window.gather_state() == {
        "chat_font_size": FONT_DEFAULT,
        "chat_red_text": False,
    }
    window.apply_state({"chat_font_size": 24, "chat_red_text": True})
    assert window.gather_state() == {"chat_font_size": 24, "chat_red_text": True}
    assert window.view.font().pointSize() == 24


def test_participant_window_tolerates_malformed_state(qtbot, headless_session):
    window = ParticipantChatWindow(headless_session)
    qtbot.addWidget(window)
    window.apply_state({"chat_font_size": "huge"})  # hand-edited study: keep default
    assert window.gather_state()["chat_font_size"] == FONT_DEFAULT
    window.apply_state({"chat_font_size": 999})  # clamped into the sane band
    assert window.gather_state()["chat_font_size"] == FONT_MAX


def test_participant_window_is_always_dark_and_red_shiftable(qtbot, headless_session):
    window = ParticipantChatWindow(headless_session)
    qtbot.addWidget(window)
    assert "#c8c8c8" in window.styleSheet()  # dim neutral gray on near-black
    window._red_action.setChecked(True)
    assert "#cc7766" in window.styleSheet()  # red-shifted night text


def test_participant_window_banner_tracks_keyboard_focus(
    qtbot, headless_session, monkeypatch
):
    window = ParticipantChatWindow(headless_session)
    qtbot.addWidget(window)
    monkeypatch.setattr(ParticipantChatWindow, "isActiveWindow", lambda self: True)
    window._refresh_keyboard_banner()
    assert "keyboard is yours" in window.keyboardBanner.text()
    monkeypatch.setattr(ParticipantChatWindow, "isActiveWindow", lambda self: False)
    window._refresh_keyboard_banner()
    assert "not here" in window.keyboardBanner.text()


def test_participant_enter_sends_and_clears(qtbot, headless_session):
    window = ParticipantChatWindow(headless_session)
    qtbot.addWidget(window)
    window.entry.setText("I'm awake")
    qtbot.keyClick(window.entry, QtCore.Qt.Key.Key_Return)
    assert window._transcript.messages == [(PARTICIPANT, "I'm awake")]
    assert window.entry.text() == ""
    assert "You:  I'm awake" in window.view.toPlainText()


# ----- experimenter view (Chat window) + the shared transcript -----------------


def test_chat_send_clears_entry_and_renders(qtbot, headless_session):
    panel = ChatWindow(headless_session)
    qtbot.addWidget(panel)
    panel.chatEntry.setText("hello")
    panel.send_chat_message()
    assert panel.chatEntry.text() == ""
    assert "You:  hello" in panel.chatView.toPlainText()


def test_chat_pass_keyboard_emits_even_with_empty_entry(qtbot, headless_session):
    panel = ChatWindow(headless_session)
    qtbot.addWidget(panel)
    fired: list[bool] = []
    panel.open_participant_chat.connect(lambda: fired.append(True))
    panel.send_and_pass_keyboard()  # nothing typed: pass the keyboard, post nothing
    assert fired == [True]
    assert panel.chatView.toPlainText() == ""


def test_transcript_is_shared_between_both_views(qtbot, headless_session):
    transcript = ChatTranscript()
    chat = ChatWindow(headless_session, transcript)
    participant = ParticipantChatWindow(headless_session, transcript)
    qtbot.addWidget(chat)
    qtbot.addWidget(participant)
    chat.chatEntry.setText("Are you awake?")
    chat.send_chat_message()
    assert "Experimenter:  Are you awake?" in participant.view.toPlainText()
    participant.entry.setText("yes")
    qtbot.keyClick(participant.entry, QtCore.Qt.Key.Key_Return)
    assert "Participant:  yes" in chat.chatView.toPlainText()


# ----- quick-reply presets (#112) ---------------------------------------------


def test_chat_presets_seed_defaults_and_round_trip():
    presets = ChatPresets()
    # Seeded from the config defaults (cleaned), and gathered back verbatim.
    assert presets.experimenter == _clean_presets(config.CHAT_EXPERIMENTER_PRESETS)
    assert presets.participant == _clean_presets(config.CHAT_PARTICIPANT_PRESETS)
    assert presets.gather_state() == {
        "chat_experimenter_presets": presets.experimenter,
        "chat_participant_presets": presets.participant,
    }
    # A present list replaces; an absent key keeps the current (default) list.
    presets.apply_state({"chat_experimenter_presets": ["Are you awake?"]})
    assert presets.experimenter == ["Are you awake?"]
    assert presets.participant == _clean_presets(config.CHAT_PARTICIPANT_PRESETS)
    # An explicitly empty list is respected as a deliberately cleared one.
    presets.apply_state({"chat_participant_presets": []})
    assert presets.participant == []


def test_chat_presets_cap_participant_and_tolerate_garbage():
    presets = ChatPresets()
    presets.apply_state(
        {
            "chat_participant_presets": [f"reply {i}" for i in range(20)],
            "chat_experimenter_presets": "not a list",  # hand-edited junk
        }
    )
    assert len(presets.participant) == config.MAX_PARTICIPANT_PRESETS
    assert presets.experimenter == []  # coerced to empty rather than crashing a load


def test_chat_preset_button_sends_through_chat_path(headless_session):
    records = _capture_session_log(headless_session)
    presets = ChatPresets()
    presets.set(["Are you awake?"], [])
    panel = ChatWindow(headless_session, presets=presets)
    assert len(panel._preset_buttons) == 1
    panel._preset_buttons[0].click()
    assert "You:  Are you awake?" in panel.chatView.toPlainText()
    messages = [r.getMessage() for r in records]
    assert "Chat to participant: Are you awake?" in messages
    assert all(r.levelno == logging.DEBUG for r in records)  # log-only by default


def test_participant_number_key_sends_only_when_entry_empty(qtbot, headless_session):
    presets = ChatPresets()
    presets.set([], ["I'm awake", "Got it"])
    window = ParticipantChatWindow(headless_session, presets=presets)
    qtbot.addWidget(window)
    assert len(window._preset_buttons) == 2
    # Empty entry: a bare number key sends the matching reply (key not typed).
    qtbot.keyClick(window.entry, QtCore.Qt.Key.Key_2)
    assert window._transcript.messages == [(PARTICIPANT, "Got it")]
    assert window.entry.text() == ""
    # With text already typed, digits type normally — no preset fires.
    window.entry.setText("3")
    qtbot.keyClick(window.entry, QtCore.Qt.Key.Key_1)
    assert window._transcript.messages == [(PARTICIPANT, "Got it")]  # unchanged
    assert window.entry.text() == "31"


def test_presets_shared_object_updates_both_views(qtbot, headless_session):
    presets = ChatPresets()
    chat = ChatWindow(headless_session, presets=presets)
    participant = ParticipantChatWindow(headless_session, presets=presets)
    qtbot.addWidget(chat)
    qtbot.addWidget(participant)
    presets.set(["Are you awake?"], ["Yes", "No"])
    # One shared object; both views rebuilt from its `changed` signal.
    assert [b.toolTip() for b in chat._preset_buttons] == ["Are you awake?"]
    assert len(participant._preset_buttons) == 2
    assert participant._preset_buttons[0].text() == "1.  Yes"


# ----- main-window wiring -----------------------------------------------------


def test_window_wires_chat_panel_without_launcher_button(
    qtbot, headless_session, mock_devices, silence_dialogs, monkeypatch
):
    monkeypatch.setattr(winvolume, "endpoint_volume", lambda: None)
    monkeypatch.setattr(winvolume, "app_volume", lambda: None)
    window = SmaccWindow(headless_session)
    qtbot.addWidget(window)
    # The participant window has no Tools-column button; the Chat window does.
    assert "participant_chat" not in SmaccWindow.PANEL_LABELS
    participant = window.panels["participant_chat"]
    assert isinstance(participant, ParticipantChatWindow)
    # The Chat window's signal opens (and would focus) the participant window.
    chat = window.panels["chat"]
    assert isinstance(chat, ChatWindow)
    assert not participant.isVisible()
    chat.open_participant_chat.emit()
    assert participant.isVisible()
    # One transcript spans both views.
    chat.chatEntry.setText("hi")
    chat.send_chat_message()
    assert "Experimenter:  hi" in participant.view.toPlainText()
    # The participant window's interface state travels with the study settings.
    state = window.gather_settings()
    assert state["chat_font_size"] == FONT_DEFAULT
    assert state["chat_red_text"] is False
    assert "participant_chat" in state["tool_always_on_top"]
    # The quick-reply presets travel too (persisted by the Chat window).
    assert state["chat_experimenter_presets"] == chat._presets.experimenter
    assert state["chat_participant_presets"] == chat._presets.participant

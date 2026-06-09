"""Tests for the GUI log-preview handler (needs a QApplication, no hardware).

QtLogHandler marshals records onto the GUI thread via a Qt signal; in a test
everything is on one thread, so the connected slot runs synchronously during
``emit`` and the QListWidget is up to date immediately.
"""

from __future__ import annotations

import logging

from PyQt6 import QtWidgets

from smacc.qtlog import QtLogHandler


def _logger_with_handler(list_widget, name):
    logger = logging.getLogger(name)
    logger.handlers.clear()  # fresh: getLogger returns a process-wide singleton
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = QtLogHandler(list_widget)
    logger.addHandler(handler)
    return logger, handler


def test_enabled_levels_gate_which_records_appear(qtbot):
    widget = QtWidgets.QListWidget()
    qtbot.addWidget(widget)
    logger, _ = _logger_with_handler(widget, "smacc.test.levels")

    logger.debug("debug line")  # DEBUG is not in the default enabled set
    logger.info("info line")  # INFO is

    assert widget.count() == 1
    assert widget.item(0).text() == "info line"


def test_enabled_levels_can_be_narrowed(qtbot):
    widget = QtWidgets.QListWidget()
    qtbot.addWidget(widget)
    logger, handler = _logger_with_handler(widget, "smacc.test.narrow")
    handler.enabled_levels = {logging.DEBUG}

    logger.info("info line")  # now filtered out
    logger.debug("debug line")  # now shown

    assert widget.count() == 1
    assert widget.item(0).text() == "debug line"


def test_smacc_preview_false_hides_record_from_preview(qtbot):
    widget = QtWidgets.QListWidget()
    qtbot.addWidget(widget)
    logger, _ = _logger_with_handler(widget, "smacc.test.preview")

    logger.info("shown")
    logger.info("hidden", extra={"smacc_preview": False})

    assert widget.count() == 1
    assert widget.item(0).text() == "shown"

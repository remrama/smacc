"""Per-session shared state: identifiers, logging, and the LSL marker outlet.

The launcher and every modality window hold a reference to one ``SmaccSession``
so they all emit event markers and log lines through a single place.
"""

from __future__ import annotations

import logging

from pylsl import StreamInfo, StreamOutlet
from PyQt5 import QtWidgets

from .config import DEVELOPMENT_ID, PPORT_ADDRESS, PPORT_CODES, VERSION
from .paths import logs_directory


class SmaccSession:
    """Shared session context: subject/session IDs, logger, and LSL outlet."""

    def __init__(self, subject_id: str, session_id: str) -> None:
        self.subject = subject_id
        self.session = session_id
        self.pport_address = PPORT_ADDRESS
        self.portcodes = PPORT_CODES
        self.init_logger()
        self.init_lsl_stream()

    def init_logger(self) -> None:
        """Initialize the logger that writes to a per-session log file."""
        path_name = f"sub-{self.subject}_ses-{self.session}_smacc-{VERSION}.log"
        log_path = logs_directory / path_name
        self.log_path = log_path  # kept for BIDS events export
        self.logger = logging.getLogger("smacc")
        self.logger.setLevel(logging.DEBUG)
        # Don't bubble up to the root logger (keeps everything out of the
        # terminal; the file/preview handlers are the only outputs).
        self.logger.propagate = False
        # open file handler to save external file
        write_mode = "w" if self.subject == DEVELOPMENT_ID else "x"
        fh = logging.FileHandler(log_path, mode=write_mode, encoding="utf-8")
        fh.setLevel(logging.DEBUG)  # the file always records every level
        formatter = logging.Formatter(
            fmt="%(asctime)s.%(msecs)03d, %(levelname)s, %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

    def init_lsl_stream(self, stream_id: str = "myuidw43536") -> None:
        """Create the LSL marker stream and its outlet."""
        self.info = StreamInfo("MyMarkerStream", "Markers", 1, 0, "string", stream_id)
        self.outlet = StreamOutlet(self.info)

    def send_event_marker(self, portcode: int, port_msg: str) -> None:
        """Push an LSL marker and log it to the file + preview."""
        self.outlet.push_sample([str(portcode)])
        self.log_info_msg(f"{port_msg} - portcode {portcode}")

    def log_info_msg(self, msg: str) -> None:
        """Log an INFO message (always to file; to the preview if INFO is on)."""
        self.logger.info(msg)

    def show_error_popup(self, short_msg, long_msg=None, parent=None) -> None:
        """Record an error in the log and show a dialog (parented if given)."""
        # Record the error in the log file (and preview if Error is enabled).
        self.logger.error(short_msg if long_msg is None else f"{short_msg} {long_msg}")
        win = QtWidgets.QMessageBox(parent)  # parent so it stacks above its window
        win.setText(short_msg)
        if long_msg is not None:
            win.setInformativeText(long_msg)
        win.setWindowTitle("Error")
        win.exec()

"""The EEG review tool: post-hoc trace viewing and annotation (#136).

This subpackage is SMACC's *optional* EEG component. It opens a recorded EEG
file (EDF, BrainVision, FIF), scrolls its traces, applies display-only filters,
and saves named annotations to a TSV sidecar — the source file is never
modified. It is a review tool, not a real-time display: nothing here runs
during a live session, and nothing in the live-session path imports from here.

The component always runs as its own process with its own ``QApplication``.
The base ``SMACC.exe`` does not bundle MNE, so an in-process viewer is
impossible in the packaged app; keeping development behavior identical gives
one code path and isolates the heavy MNE/pyqtgraph process from the
lab-critical session app.

Layout keeps the heavy dependency at the edges: :mod:`~smacc.eeg.annotations`
(the model and sidecar I/O) and :mod:`~smacc.eeg.dsp` (display filtering) are
pure Python over numpy/scipy and import no MNE; :mod:`~smacc.eeg.io` is the
only module that touches MNE, and imports it lazily. This module itself stays
import-light so the base app can probe for the component without paying for it.
"""

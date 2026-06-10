r"""Windows file-association for ``.smacc`` study files (per-user, no admin).

Registers SMACC as the handler for ``.smacc`` under ``HKCU\Software\Classes`` so a
double-clicked study opens the app already configured. Per-user keys need no admin
rights and are reliable for a novel extension (nothing else claims ``.smacc``). Only
meaningful for the packaged Windows ``.exe`` — :func:`is_associatable` gates it (a
dev run's ``sys.executable`` is python.exe, which must not be registered).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

EXT = ".smacc"
PROGID = "SMACC.Study"
FRIENDLY_NAME = "SMACC study configuration"
CONTENT_TYPE = "application/x-smacc"


def association_entries(exe_path: str) -> list[tuple[str, str, str]]:
    """Return the ``(subkey, value_name, value_data)`` triples to write under HKCU.

    Pure (no I/O) so the registry layout — the ProgID, the quoted ``"%1"`` command,
    and the icon reference — is unit-testable without touching the registry. Both the
    exe path and ``%1`` are quoted because study/exe paths contain spaces.
    """
    classes = r"Software\Classes"
    command = f'"{exe_path}" "%1"'
    icon = f'"{exe_path}",0'
    return [
        (rf"{classes}\{EXT}", "", PROGID),
        (rf"{classes}\{EXT}", "Content Type", CONTENT_TYPE),
        (rf"{classes}\{PROGID}", "", FRIENDLY_NAME),
        (rf"{classes}\{PROGID}\DefaultIcon", "", icon),
        (rf"{classes}\{PROGID}\shell\open\command", "", command),
    ]


def is_associatable() -> bool:
    """True only for the packaged Windows build (a dev run uses python.exe)."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def is_registered(exe_path: str | None = None) -> bool:
    """True if ``.smacc`` is already associated with this SMACC executable.

    Reads the per-user keys :func:`register_smacc` writes and confirms the extension
    maps to our ProgID whose open command invokes ``exe_path`` (this build's exe by
    default). Lets the first-run prompt skip itself when the association is already in
    place, so a re-launch — even one whose preferences didn't persist — doesn't ask
    again. A non-Windows platform, a missing key, or any read error reads as "not
    registered" (so the worst case is offering an association that's already set).
    """
    if sys.platform != "win32":
        return False
    import winreg

    if exe_path is None:
        exe_path = os.fspath(Path(sys.executable).resolve())
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{EXT}"
        ) as key:
            progid, _ = winreg.QueryValueEx(key, "")
        if progid != PROGID:
            return False
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{PROGID}\shell\open\command"
        ) as key:
            command, _ = winreg.QueryValueEx(key, "")
    except OSError:
        return False
    return command == f'"{exe_path}" "%1"'


def register_smacc(exe_path: str | None = None) -> None:
    """Register the per-user ``.smacc`` association and refresh the shell.

    Raises:
        OSError: on a non-Windows platform or if a registry write fails.
    """
    if sys.platform != "win32":
        raise OSError("File association is only supported on Windows.")
    import winreg

    if exe_path is None:
        exe_path = os.fspath(Path(sys.executable).resolve())
    for subkey, name, data in association_entries(exe_path):
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_WRITE
        ) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, data)

    # Tell Explorer the association changed so the icon/handler refresh promptly.
    try:
        import ctypes

        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )
    except Exception:  # cosmetic icon-cache refresh; never fatal
        pass

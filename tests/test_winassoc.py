"""Tests for the .smacc Windows association layout (pure; no registry writes)."""

import re
from pathlib import Path

from smacc import winassoc


def test_association_entries_layout():
    table = {
        (key, name): data
        for key, name, data in winassoc.association_entries(r"C:\Apps\SMACC.exe")
    }
    assert table[(r"Software\Classes\.smacc", "")] == "SMACC.Study"
    assert (
        table[(r"Software\Classes\SMACC.Study\shell\open\command", "")]
        == r'"C:\Apps\SMACC.exe" "%1"'
    )
    assert (
        table[(r"Software\Classes\SMACC.Study\DefaultIcon", "")]
        == r'"C:\Apps\SMACC.exe",0'
    )


def test_command_quotes_exe_and_percent_one():
    entries = winassoc.association_entries(r"C:\Program Files\SMACC\SMACC.exe")
    command = next(d for k, _n, d in entries if k.endswith(r"open\command"))
    assert command == r'"C:\Program Files\SMACC\SMACC.exe" "%1"'
    assert command.count('"') == 4  # exe quoted + %1 quoted (spaces safe)


def test_is_associatable_false_under_pytest():
    # Not a frozen build, so this must be False — guards against CI registry writes.
    assert winassoc.is_associatable() is False


def test_is_registered_false_for_unknown_exe():
    # Nothing associates .smacc with this throwaway path (and on non-Windows the
    # check is always False), so it must read as not registered. No registry writes.
    assert winassoc.is_registered(r"C:\Nope\DoesNotExist\SMACC.exe") is False


def test_installer_registry_section_matches_association_entries():
    # The installer (tools/smacc.iss) writes the association itself so that
    # is_registered() finds it and the in-app first-run prompt skips itself. That
    # only works while its [Registry] section and association_entries() agree
    # exactly — value for value — so cross-check them here to catch drift.
    iss_text = (Path(__file__).parent.parent / "tools" / "smacc.iss").read_text(
        encoding="utf-8"
    )
    # Inno escapes a literal quote inside a quoted parameter by doubling it.
    quoted = r'"((?:[^"]|"")*)"'
    entry_re = re.compile(
        rf"^Root: HKA; Subkey: {quoted}; ValueType: string; "
        rf"ValueName: {quoted}; ValueData: {quoted}",
        re.MULTILINE,
    )
    found = [
        tuple(field.replace('""', '"') for field in match.groups())
        for match in entry_re.finditer(iss_text)
    ]
    expected = winassoc.association_entries(r"{app}\SMACC.exe")
    assert sorted(found) == sorted(expected)

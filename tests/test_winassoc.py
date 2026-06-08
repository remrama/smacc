"""Tests for the .smacc Windows association layout (pure; no registry writes)."""

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

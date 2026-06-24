"""Tests for the hardware-trigger config and send logic (#28); no real hardware."""

import pytest

from smacc import triggers

# ----- TriggerConfig serialization ------------------------------------------


def test_default_config_is_disabled_lsl_only():
    cfg = triggers.TriggerConfig()
    assert cfg.enabled is False
    assert cfg.transport == "serial"
    assert cfg.mode == "pulsed"
    assert "disabled" in cfg.summary()


def test_config_round_trips_through_dict():
    cfg = triggers.TriggerConfig(
        enabled=True,
        transport="parallel",
        port="COM7",
        baud=9600,
        address="0x278",
        mode="hold",
        pulse_ms=5,
    )
    assert triggers.from_dict(cfg.to_dict()) == cfg


def test_from_dict_missing_or_garbage_falls_back_to_defaults():
    assert triggers.from_dict(None) == triggers.TriggerConfig()
    assert triggers.from_dict("nope") == triggers.TriggerConfig()
    # Unknown transport/mode and unparseable numbers fall back, never raise.
    cfg = triggers.from_dict(
        {"transport": "carrier-pigeon", "mode": "warble", "baud": "fast", "pulse_ms": 0}
    )
    assert cfg.transport == triggers.DEFAULT_TRANSPORT
    assert cfg.mode == triggers.DEFAULT_MODE
    assert cfg.baud == triggers.DEFAULT_BAUD
    assert cfg.pulse_ms == 1  # clamped to a minimum of 1 ms


def test_load_reads_trigger_output_block():
    assert triggers.load({}) == triggers.TriggerConfig()  # absent → default
    cfg = triggers.load({"trigger_output": {"enabled": True, "port": "COM3"}})
    assert cfg.enabled is True
    assert cfg.port == "COM3"


# ----- parse_address --------------------------------------------------------


def test_parse_address_accepts_hex_decimal_and_int():
    assert triggers.parse_address("0x378") == 0x378
    assert triggers.parse_address("888") == 888  # bare digits are decimal
    assert triggers.parse_address(0x278) == 0x278


@pytest.mark.parametrize("bad", ["nope", "0xZZ", True])
def test_parse_address_rejects_garbage(bad):
    with pytest.raises(triggers.TriggerError):
        triggers.parse_address(bad)


# ----- pulse vs. hold timing ------------------------------------------------


def test_pulsed_writes_code_then_zero():
    writes, waits = [], []
    sender = triggers._PulseSender(writes.append, "pulsed", 0.01, sleep=waits.append)
    sender.send(42)
    assert writes == [42, 0]  # raise the code, then drop the line
    assert waits == [0.01]  # waited the pulse width between the two writes


def test_hold_writes_code_only():
    writes, waits = [], []
    sender = triggers._PulseSender(writes.append, "hold", 0.01, sleep=waits.append)
    sender.send(42)
    assert writes == [42]  # set and leave it; no drop, no wait
    assert waits == []


# ----- open_trigger routing -------------------------------------------------


def test_open_trigger_disabled_returns_none():
    assert triggers.open_trigger(triggers.TriggerConfig(enabled=False)) is None


def test_open_trigger_unknown_transport_raises():
    cfg = triggers.TriggerConfig(enabled=True)
    cfg.transport = "telepathy"  # bypasses from_dict's guard, as a hand-edit might
    with pytest.raises(triggers.TriggerError):
        triggers.open_trigger(cfg)


def test_serial_without_port_raises_clear_error():
    cfg = triggers.TriggerConfig(enabled=True, transport="serial", port="")
    with pytest.raises(triggers.TriggerError, match="No serial port"):
        triggers.open_trigger(cfg)


# ----- transport write paths (against fakes, no hardware) -------------------


def test_serial_trigger_pulses_a_byte_then_zero(monkeypatch):
    import serial

    writes = []

    class _FakePort:
        def __init__(self, port, baud, timeout=0, write_timeout=0.5):
            self.opened = (port, baud)

        def write(self, data):
            writes.append(data)

        def flush(self):
            pass

        def close(self):
            writes.append("closed")

    monkeypatch.setattr(serial, "Serial", _FakePort)
    cfg = triggers.TriggerConfig(
        enabled=True, transport="serial", port="COM3", mode="pulsed", pulse_ms=1
    )
    out = triggers.open_trigger(cfg)
    out.send(42)
    out.close()
    assert writes == [bytes([42]), bytes([0]), "closed"]  # raise, drop, release


def test_parallel_trigger_holds_a_byte_via_fake_driver(monkeypatch):
    calls = []

    class _FakeDLL:
        def Out32(self, address, value):
            calls.append((address, value))

    monkeypatch.setattr(triggers, "_load_inpout", lambda: _FakeDLL())
    cfg = triggers.TriggerConfig(
        enabled=True, transport="parallel", address="0x378", mode="hold"
    )
    out = triggers.open_trigger(cfg)  # __init__ writes the address low first
    out.send(42)  # hold: write the code, no drop
    out.close()  # returns the line to low
    assert calls == [(0x378, 0), (0x378, 42), (0x378, 0)]


# ----- misc -----------------------------------------------------------------


def test_summary_describes_each_transport():
    serial = triggers.TriggerConfig(enabled=True, transport="serial", port="COM3")
    assert "COM3" in serial.summary() and "serial" in serial.summary()
    parallel = triggers.TriggerConfig(
        enabled=True, transport="parallel", address="0x378"
    )
    assert "0x378" in parallel.summary()


def test_list_serial_ports_returns_a_list():
    # No hardware is required; on a port-less CI box this is just empty.
    assert isinstance(triggers.list_serial_ports(), list)


def test_parallel_driver_available_reflects_dll_load(monkeypatch):
    def _no_driver():
        raise triggers.TriggerError("not installed")

    monkeypatch.setattr(triggers, "_load_inpout", _no_driver)
    assert triggers.parallel_driver_available() is False
    monkeypatch.setattr(triggers, "_load_inpout", lambda: object())
    assert triggers.parallel_driver_available() is True


# ----- study/rig split (#300) ------------------------------------------------


def test_to_study_dict_omits_machine_fields():
    cfg = triggers.TriggerConfig(
        enabled=True, transport="serial", port="COM3", baud=9600, address="0x278"
    )
    study = cfg.to_study_dict()
    assert study == {
        "enabled": True,
        "transport": "serial",
        "mode": "pulsed",
        "pulse_ms": 10,
    }
    assert not {"port", "baud", "address"} & set(study)  # machine fields omitted


def test_to_rig_dict_is_machine_fields_only():
    cfg = triggers.TriggerConfig(port="COM3", baud=9600, address="0x278")
    assert cfg.to_rig_dict() == {"port": "COM3", "baud": 9600, "address": "0x278"}


def test_from_study_and_rig_combines_behavior_and_machine():
    study = {
        "trigger_output": {
            "enabled": True,
            "transport": "serial",
            "mode": "pulsed",
            "pulse_ms": 5,
        }
    }
    cfg = triggers.from_study_and_rig(
        study, {"port": "COM7", "baud": 9600, "address": "0x3F8"}
    )
    assert cfg.enabled is True
    assert cfg.transport == "serial"
    assert cfg.pulse_ms == 5
    assert cfg.port == "COM7"
    assert cfg.baud == 9600
    assert cfg.address == "0x3F8"


def test_from_study_and_rig_empty_rig_leaves_study_values():
    study = {"trigger_output": {"enabled": True, "port": "COM1"}}
    cfg = triggers.from_study_and_rig(study, {})
    # No rig machine fields → keep whatever from_dict produced (defaults / legacy).
    assert cfg.port == "COM1"  # a legacy study port survives when the rig has none
    assert cfg.baud == triggers.DEFAULT_BAUD

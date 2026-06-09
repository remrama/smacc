"""Optional hardware TTL trigger output alongside the LSL marker stream (#28).

SMACC always emits event markers over LSL; this module adds an *opt-in* second
path that drives a physical trigger, so amplifiers that ingest a TTL pulse (rather
than a network marker) still see every port code. The byte sent stays inside the
8-bit port-code contract (:mod:`smacc.events`), so existing EEG marker maps line up.

One transport at a time, selected and configured per study (persisted in the
``.smacc`` file, edited in the Trigger output dialog):

* ``serial`` — write the code as a single byte to a COM port with `pyserial`. The
  modern path: a USB-serial trigger box mirrors the received byte onto 8 TTL lines.
* ``parallel`` — write the byte to an LPT data register through the InpOut32 /
  inpoutx64 kernel driver (via :mod:`ctypes`). The driver must be installed
  manually; SMACC never downloads it (see the Triggers docs and the issue history).

Both transports support two pulse behaviors, because rigs differ — pick in config:

* ``pulsed`` — raise ``code`` on the lines, wait ``pulse_ms``, then drop to 0. SMACC
  times the pulse itself. Use for amps/boxes that expect a brief marker pulse.
* ``hold`` — write ``code`` once and leave the lines there until the next event.
  Use for true set-and-hold amps *and* for boxes that pulse on their own fixed
  width (SMACC just sets the value; the box shapes the pulse).

Every default here is a sane, generalizable starting point — no rig is assumed; all
of it is editable in the GUI. This module is Qt-free and unit-testable: the GUI
builds/edits a :class:`TriggerConfig`, and the session opens it via
:func:`open_trigger` into something satisfying :class:`TriggerOutput`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any, Protocol, runtime_checkable

# Defaults: editable per study, so these are only the out-of-the-box starting point.
DEFAULT_TRANSPORT = "serial"
DEFAULT_BAUD = 115200
# The classic LPT1 base address. Real rigs vary (an add-in parallel card maps
# elsewhere); confirm yours in Device Manager and override it — see the Triggers docs.
DEFAULT_LPT_ADDRESS = "0x378"
DEFAULT_MODE = "pulsed"
DEFAULT_PULSE_MS = 10

TRANSPORTS = ("serial", "parallel")
MODES = ("pulsed", "hold")

# The idle/"off" value written between and after pulses. The port-code contract
# reserves 1..255 for events, so 0 is always a safe low state.
_OFF = 0


class TriggerError(Exception):
    """A hardware trigger transport could not be opened or written to.

    Carries a human-readable, actionable message (missing driver, busy port, …);
    the window shows it to the operator verbatim.
    """


@runtime_checkable
class TriggerOutput(Protocol):
    """A live hardware trigger transport: send a port code, then release it."""

    def send(self, code: int) -> None: ...

    def close(self) -> None: ...


@dataclass
class TriggerConfig:
    """How (and whether) to mirror each port code onto a hardware trigger line.

    LSL marker output is always on and independent of this; these settings drive the
    *optional* second path. Persisted as the ``trigger_output`` block of a study.
    """

    enabled: bool = False
    transport: str = DEFAULT_TRANSPORT  # one of TRANSPORTS
    port: str = ""  # serial COM port, e.g. "COM3"
    baud: int = DEFAULT_BAUD
    address: str = DEFAULT_LPT_ADDRESS  # parallel-port base address (hex string)
    mode: str = DEFAULT_MODE  # one of MODES
    pulse_ms: int = DEFAULT_PULSE_MS

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the plain mapping persisted in a study file."""
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def summary(self) -> str:
        """A one-line human description for logs and the dialog (e.g. on a change)."""
        if not self.enabled:
            return "disabled (LSL only)"
        if self.transport == "serial":
            where = f"{self.port or '(no port)'} @ {self.baud} baud"
        else:
            where = f"LPT {self.address}"
        pulse = f"{self.mode}" + (
            f" {self.pulse_ms} ms" if self.mode == "pulsed" else ""
        )
        return f"{self.transport} — {where}, {pulse}"


def _coerce_int(value: object, default: int) -> int:
    """Best-effort int from a persisted value; ``default`` on anything unparseable."""
    if isinstance(value, bool):  # bool is an int subclass; never a valid code/baud
        return default
    try:
        return int(value)  # type: ignore[call-overload]  # guarded by except
    except (TypeError, ValueError):
        return default


def from_dict(data: object) -> TriggerConfig:
    """Build a :class:`TriggerConfig` from a persisted mapping, coercing each field.

    Mirrors the defensive merge-over-defaults used elsewhere (events/devices): a
    missing block, an unknown transport/mode, or a malformed value falls back to the
    default, so a hand-edited or older study never breaks the load.
    """
    cfg = TriggerConfig()
    if not isinstance(data, dict):
        return cfg
    cfg.enabled = bool(data.get("enabled", False))
    if data.get("transport") in TRANSPORTS:
        cfg.transport = data["transport"]
    cfg.port = str(data.get("port") or "")
    cfg.baud = _coerce_int(data.get("baud"), DEFAULT_BAUD)
    address = data.get("address")
    cfg.address = str(address) if address else DEFAULT_LPT_ADDRESS
    if data.get("mode") in MODES:
        cfg.mode = data["mode"]
    cfg.pulse_ms = max(1, _coerce_int(data.get("pulse_ms"), DEFAULT_PULSE_MS))
    return cfg


def load(settings: dict) -> TriggerConfig:
    """Return the trigger config from a study's settings mapping (default if absent)."""
    return from_dict(settings.get("trigger_output"))


def parse_address(address: str | int) -> int:
    """Parse an LPT base address: a hex string (``"0x378"``), decimal string, or int.

    Hex must carry the ``0x`` prefix; bare digits are read as decimal. Raises
    :class:`TriggerError` (with guidance) on anything else.
    """
    if isinstance(address, bool):
        raise TriggerError(f"Invalid parallel-port address {address!r}.")
    if isinstance(address, int):
        return address
    text = str(address).strip()
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text, 10)
    except ValueError as exc:
        raise TriggerError(
            f"Invalid parallel-port address {address!r} (use hex like 0x378)."
        ) from exc


class _PulseSender:
    """Shared pulse/hold logic over a single ``write(value)`` function.

    ``pulsed`` writes ``code`` then 0 after ``pulse_s`` (a marker pulse SMACC times);
    ``hold`` writes ``code`` once. The sleep is injectable so tests don't actually
    wait. The rising edge — the write of ``code`` — is what the amplifier timestamps,
    and it happens first, so the (brief) sleep never costs marker precision.
    """

    def __init__(
        self,
        write: Callable[[int], None],
        mode: str,
        pulse_s: float,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._write = write
        self._mode = mode
        self._pulse_s = pulse_s
        self._sleep = sleep

    def send(self, code: int) -> None:
        self._write(code)
        if self._mode == "pulsed":
            self._sleep(self._pulse_s)
            self._write(_OFF)


class SerialTrigger:
    """Write each port code as one byte to a serial (USB) trigger box."""

    def __init__(self, config: TriggerConfig) -> None:
        try:
            import serial  # pyserial; imported lazily so non-serial rigs need no dep
        except ImportError as exc:  # pragma: no cover - pyserial is a hard dep
            raise TriggerError(
                "Serial trigger output needs pyserial, which isn't installed."
            ) from exc
        if not config.port:
            raise TriggerError("No serial port selected for trigger output.")
        try:
            # write_timeout caps how long a stuck write blocks the GUI thread, so a
            # pulled cable can't freeze a live run for long before it's disabled.
            self._serial = serial.Serial(
                config.port, config.baud, timeout=0, write_timeout=0.5
            )
        except Exception as exc:  # serial.SerialException et al.
            raise TriggerError(
                f"Could not open serial port {config.port!r}: {exc}"
            ) from exc
        self._sender = _PulseSender(self._write, config.mode, config.pulse_ms / 1000)

    def _write(self, value: int) -> None:
        self._serial.write(bytes([value & 0xFF]))
        self._serial.flush()

    def send(self, code: int) -> None:
        self._sender.send(code)

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass


class ParallelTrigger:
    """Write each port code to an LPT data register via the InpOut32 driver."""

    def __init__(self, config: TriggerConfig) -> None:
        self._address = parse_address(config.address)
        self._dll = _load_inpout()
        self._sender = _PulseSender(self._write, config.mode, config.pulse_ms / 1000)
        self._write(_OFF)  # start from a known-low state

    def _write(self, value: int) -> None:
        self._dll.Out32(self._address, value & 0xFF)

    def send(self, code: int) -> None:
        self._sender.send(code)

    def close(self) -> None:
        try:
            self._write(_OFF)
        except Exception:
            pass


def _load_inpout() -> Any:
    """Load the InpOut32 / inpoutx64 kernel-driver DLL (Windows only).

    The driver must be installed manually — SMACC never downloads it (see the
    Triggers docs and the issue history). ``WinDLL`` is fetched via ``getattr`` so
    this module also type-checks on non-Windows CI, where the attribute is absent.
    """
    import ctypes

    win_dll: Any = getattr(ctypes, "WinDLL", None)
    if win_dll is None:
        raise TriggerError("Parallel-port output is only available on Windows.")
    for name in ("inpoutx64.dll", "inpout32.dll"):
        try:
            dll = win_dll(name)
        except OSError:
            continue
        dll.Out32.argtypes = [ctypes.c_int16, ctypes.c_int16]
        dll.Out32.restype = None
        return dll
    raise TriggerError(
        "Parallel-port output needs the InpOut32 driver (inpoutx64.dll), which "
        "could not be loaded. Install it manually and place inpoutx64.dll on the "
        "system path — see the Triggers docs. SMACC will not download it."
    )


def open_trigger(config: TriggerConfig) -> TriggerOutput | None:
    """Open the configured transport, or ``None`` when disabled.

    Raises :class:`TriggerError` (with an actionable message) when an *enabled*
    transport can't be opened — a missing driver, a busy/absent port, a bad address.
    """
    if not config.enabled:
        return None
    if config.transport == "serial":
        return SerialTrigger(config)
    if config.transport == "parallel":
        return ParallelTrigger(config)
    raise TriggerError(f"Unknown trigger transport {config.transport!r}.")


def list_serial_ports() -> list[tuple[str, str]]:
    """Return ``[(device, description), …]`` for attached serial ports (``[]`` on error).

    Used to populate the port dropdown; never raises, so a backend hiccup can't block
    the dialog.
    """
    try:
        from serial.tools import list_ports
    except ImportError:  # pragma: no cover - pyserial is a hard dep
        return []
    try:
        return [(p.device, p.description or p.device) for p in list_ports.comports()]
    except Exception:  # pragma: no cover - defensive against backend quirks
        return []

"""Tests for the Philips Hue client and visual-cue backend (no network).

Every bridge call goes through the one ``hue._http_json`` seam; these tests stub
it with canned replies (or transport failures) and assert the client's behavior.
"""

from __future__ import annotations

import pytest

from smacc import hue

CFG = hue.HueConfig(bridge_ip="192.168.1.50", app_key="testkey")


def _stub_http(monkeypatch, handler):
    """Route hue._http_json through ``handler(method, url, payload)``."""
    calls: list[tuple[str, str, dict | None]] = []

    def fake(method, url, payload=None):
        calls.append((method, url, payload))
        return handler(method, url, payload)

    monkeypatch.setattr(hue, "_http_json", fake)
    return calls


# ----- config ---------------------------------------------------------------


def test_config_round_trips_and_tolerates_junk():
    assert hue.from_dict(CFG.to_dict()) == CFG
    assert hue.from_dict(None) == hue.HueConfig()
    assert hue.from_dict({"bridge_ip": 5, "app_key": None}) == hue.HueConfig("5", "")
    assert hue.load({"hue": CFG.to_dict()}) == CFG
    assert hue.load({}) == hue.HueConfig()


def test_configured_requires_both_fields():
    assert CFG.configured
    assert not hue.HueConfig(bridge_ip="1.2.3.4").configured
    assert not hue.HueConfig(app_key="k").configured


# ----- discovery + pairing ----------------------------------------------------


def test_discover_returns_bridge_ips(monkeypatch):
    _stub_http(
        monkeypatch,
        lambda *a: [{"id": "abc", "internalipaddress": "10.0.0.7"}, {"id": "x"}],
    )
    assert hue.discover() == ["10.0.0.7"]


def test_discover_swallows_transport_errors(monkeypatch):
    def boom(*a):
        raise hue.HueError("down")

    _stub_http(monkeypatch, boom)
    assert hue.discover() == []


def test_pair_returns_the_minted_key(monkeypatch):
    calls = _stub_http(monkeypatch, lambda *a: [{"success": {"username": "newkey"}}])
    assert hue.pair("10.0.0.7") == "newkey"
    method, url, payload = calls[0]
    assert (method, url) == ("POST", "http://10.0.0.7/api")
    assert payload is not None and payload["devicetype"].startswith("smacc#")


def test_pair_guides_when_link_button_not_pressed(monkeypatch):
    _stub_http(
        monkeypatch,
        lambda *a: [{"error": {"type": 101, "description": "link button not pressed"}}],
    )
    with pytest.raises(hue.HueError, match="link button"):
        hue.pair("10.0.0.7")


def test_pair_surfaces_other_bridge_errors(monkeypatch):
    _stub_http(monkeypatch, lambda *a: [{"error": {"type": 7, "description": "nope"}}])
    with pytest.raises(hue.HueError, match="nope"):
        hue.pair("10.0.0.7")


# ----- enumeration ---------------------------------------------------------------


def test_targets_lists_lights_then_groups(monkeypatch):
    def handler(method, url, payload):
        if url.endswith("/lights"):
            return {"1": {"name": "Bed lamp"}, "10": {"name": "Ceiling"}}
        return {"1": {"name": "Bedroom"}}

    _stub_http(monkeypatch, handler)
    assert hue.targets(CFG) == [
        ("Bed lamp (light 1)", "light:1"),
        ("Ceiling (light 10)", "light:10"),
        ("Bedroom (group 1)", "group:1"),
    ]


def test_targets_without_config_is_empty_and_offline(monkeypatch):
    calls = _stub_http(monkeypatch, lambda *a: pytest.fail("should not call"))
    assert hue.targets(hue.HueConfig()) == []
    assert calls == []


def test_targets_surfaces_bridge_errors(monkeypatch):
    _stub_http(
        monkeypatch,
        lambda *a: [{"error": {"type": 1, "description": "unauthorized user"}}],
    )
    with pytest.raises(hue.HueError, match="unauthorized"):
        hue.targets(CFG)


# ----- color mapping -------------------------------------------------------------


def test_rgb_to_xy_bri_hits_the_philips_primaries():
    x, y, bri = hue.rgb_to_xy_bri((255, 0, 0))
    assert (x, y) == (pytest.approx(0.7006, abs=1e-3), pytest.approx(0.2993, abs=1e-3))
    assert bri == 254
    x, y, bri = hue.rgb_to_xy_bri((255, 255, 255))
    assert (x, y) == (pytest.approx(0.3227, abs=1e-3), pytest.approx(0.3290, abs=1e-3))
    assert bri == 254


def test_rgb_to_xy_bri_scales_bri_with_the_value_component():
    _, _, bri = hue.rgb_to_xy_bri((128, 0, 0))
    assert bri == round(128 / 255 * 254)
    _, _, bri = hue.rgb_to_xy_bri((1, 0, 0))
    assert bri == 1  # clamped to the bridge's floor


# ----- backend ----------------------------------------------------------------------


def test_backend_apply_puts_color_state_to_a_light(monkeypatch):
    calls = _stub_http(monkeypatch, lambda *a: [{"success": {}}])
    backend = hue.HueBackend(CFG, "light:3")
    backend.apply((255, 0, 0))
    method, url, payload = calls[0]
    assert method == "PUT"
    assert url == "http://192.168.1.50/api/testkey/lights/3/state"
    assert payload is not None
    assert payload["on"] is True
    assert payload["bri"] == 254
    assert payload["transitiontime"] == 1
    assert payload["xy"] == [
        pytest.approx(0.7006, abs=1e-3),
        pytest.approx(0.2993, abs=1e-3),
    ]


def test_backend_black_frame_and_off_turn_the_light_off(monkeypatch):
    calls = _stub_http(monkeypatch, lambda *a: [{"success": {}}])
    backend = hue.HueBackend(CFG, "group:2")
    backend.apply((0, 0, 0))
    backend.off()
    (_, url1, p1), (_, url2, p2) = calls
    assert url1 == url2 == "http://192.168.1.50/api/testkey/groups/2/action"
    assert p1 == {"on": False, "transitiontime": 1}
    assert p2 == {"on": False, "transitiontime": 0}


def test_backend_raises_on_bridge_refusal(monkeypatch):
    _stub_http(monkeypatch, lambda *a: [{"error": {"description": "resource down"}}])
    backend = hue.HueBackend(CFG, "light:1")
    with pytest.raises(hue.HueError, match="resource down"):
        backend.apply((10, 10, 10))


def test_backend_declares_no_flash_support():
    assert hue.HueBackend(CFG, "light:1").supports_flash is False


def test_resolve_backend_requires_config_and_binding():
    assert hue.resolve_backend(hue.HueConfig(), "light:1") is None
    assert hue.resolve_backend(CFG, "") is None
    assert isinstance(hue.resolve_backend(CFG, "light:1"), hue.HueBackend)

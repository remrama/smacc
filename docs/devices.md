# Compatible devices

SMACC can drive a small number of external devices for cueing. This page lists
the supported hardware and what each one needs. For how SMACC *assigns and routes*
devices — roles, the Devices window, and volume — see
[Audio & device routing](audio.md).

## BlinkStick

[BlinkStick](https://www.blinkstick.com/) is a USB-controlled RGB LED device.
SMACC uses it for **visual cues** — lighting up a chosen color, steady or
pulsing/flashing, for a set duration — which is handy for light-based cueing in
sleep and lucid-dreaming experiments.

### What you need

* **A BlinkStick device.** They are sold directly from
  [blinkstick.com](https://www.blinkstick.com/). SMACC drives them through the
  [`blinkstick`](https://pypi.org/project/BlinkStick/) Python library, so any
  model that library supports (BlinkStick Square, Strip, Nano, Flex, …) will work.
* **Nothing else to install.** The BlinkStick driver is bundled inside
  `SMACC.exe`, so you only need to plug the device into a USB port before
  launching SMACC.

### Using it in SMACC

1. Plug the BlinkStick into a USB port, then launch SMACC.
2. Click **Visual cue** in the *Tools* column.
3. Bind your BlinkStick to the **BlinkStick** role in the **Devices** window (in
   the *Tools* column). Plug one in after launch and it's detected automatically,
   or choose **File ▸ Refresh devices** (or press `F5`) to rescan.
4. Configure a light cue — color, brightness, pattern (steady, or a pulse/flash at
   a rate in Hz), and length (or **Loop** until stopped) — and add more cues with
   **+ Add cue** if the protocol needs several.
5. Click a cue's **Play** to fire it; **Stop** turns the light off early. The rest
   of SMACC stays responsive while the light is on.

Your chosen device, color, and length are saved in the `.smacc` settings file (see
[Usage › Settings files](usage.md#settings-files-smacc)), so the visual-cue setup
travels with the rest of your configuration; the device is reconnected by name on
the next launch (and flagged if it isn't plugged in).

!!! note
    If the visual cue window reports that no light is set, open the **Devices**
    window and bind one to the **BlinkStick** role (plug it in first; use
    **File ▸ Refresh devices** or `F5` if it isn't listed). No restart needed.

## Philips Hue

A [Philips Hue](https://www.philips-hue.com/) bridge is the room-scale alternative
to the BlinkStick: the visual cue drives an ordinary Hue bulb (or a whole group)
over the local network. Setup is once per bridge:

1. In the **Devices** window, click **Set up Philips Hue…**.
2. Click **Find bridge** (or type the bridge's IP — the Hue app shows it under
   bridge settings).
3. Press the round **link button** on the bridge itself, then click **Pair**
   within 30 seconds. **Test** lists the bridge's lights to confirm.
4. Bind a light or group to the **Philips Hue** role, and route **Present visual
   cue** to **Philips Hue**.

The bridge IP and pairing key are stored in the study's `.smacc` (the key is a
local-network credential — treat the file accordingly). Two constraints to know:
every command is an HTTP round-trip, so a Hue cue's onset lags its marker by tens
of milliseconds (time-locked protocols should keep the BlinkStick), and the
bridge's rate limits rule out the **flash** pattern — SMACC refuses it on Hue
rather than degrade it silently. Steady cues and slow pulses work well. A full
comparison of the two devices is coming with the visual-cues docs page
([#53](https://github.com/remrama/smacc/issues/53)).

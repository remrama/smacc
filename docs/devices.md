# Compatible devices

SMACC can drive a small number of external devices for cueing. This page lists
the supported hardware and what each one needs. For how SMACC *assigns and routes*
devices — equipment, the Devices window, and volume — see
[Audio & device routing](audio.md); for using the light devices — patterns,
timing, choosing between them, and safety — see [Visual cues](visual.md).

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
3. Bind your BlinkStick to the **BlinkStick light** equipment in the **Devices** window
   (in the *Tools* column). Plug one in after launch and it's detected
   automatically, or click **Refresh devices (F5)** in the Devices window to rescan.
4. Configure a light cue — color, brightness, pattern (steady, or a pulse/flash at
   a rate in Hz), and length (or **Loop** until stopped) — and add more cues with
   **+ Add cue** if the protocol needs several. See [Visual cues](visual.md) for
   what each pattern is for.
5. Click a cue's **Play** to fire it; **Stop** turns the light off early. The rest
   of SMACC stays responsive while the light is on.

Your chosen device and the whole cue board are saved in the
[SMACC file](smacc-files.md), so the visual-cue
setup travels with the rest of your configuration; the device is reconnected by
serial on the next launch (and flagged if it isn't plugged in).

!!! note
    If the visual cue window reports that no light is set, open the **Devices**
    window and bind one to **BlinkStick light** (plug it in first; click
    **Refresh devices (F5)** there if it isn't listed). No restart needed.

## Philips Hue

A [Philips Hue](https://www.philips-hue.com/) bridge is the room-scale alternative
to the BlinkStick: the visual cue drives an ordinary Hue bulb (or a whole group)
over the local network. Setup is once per bridge:

1. In the **Devices** window, click **Set up Philips Hue…**.
2. Click **Find bridge** (or type the bridge's IP — the Hue app shows it under
   bridge settings).
3. Press the round **link button** on the bridge itself, then click **Pair**
   within 30 seconds. **Test** lists the bridge's lights to confirm.
4. Bind a light or group to the **Philips Hue light** equipment, and route
   **Play visual cue** to **Philips Hue light**.

The bridge IP and pairing key are stored in the study's `.smacc` (the key is a
local-network credential — treat the file accordingly). Hue suits ambient,
room-scale light; it can't flash and its onsets lag their markers, so time-locked
protocols should keep the BlinkStick — see the full
[BlinkStick-vs-Hue comparison](visual.md#blinkstick-or-philips-hue), and the
network note there if the rig lives on a university Wi-Fi.

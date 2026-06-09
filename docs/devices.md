# Compatible devices

SMACC can drive a small number of external devices for cueing. This page lists
the supported hardware and what each one needs. For how SMACC *assigns and routes*
devices — roles, the Devices window, and volume — see
[Audio & device routing](audio.md).

## BlinkStick

[BlinkStick](https://www.blinkstick.com/) is a USB-controlled RGB LED device.
SMACC uses it for **visual cues** — lighting up a chosen color for a set duration
— which is handy for light-based cueing in sleep and lucid-dreaming experiments.

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
2. Click **Visual stimulation** in the *Tools* column.
3. Bind your BlinkStick to the **Bedroom lights** role in the **Devices** window (in
   the *Tools* column). Plug one in after launch and it's detected automatically,
   or choose **File ▸ Refresh devices** (or press `F5`) to rescan.
4. Pick a **Color** and a **Length** (how long the light stays on, in seconds).
5. Click **Play BlinkStick** to fire the cue.

Your chosen device, color, and length are saved in the `.smacc` settings file (see
[Usage › Settings files](usage.md#settings-files-smacc)), so the visual-cue setup
travels with the rest of your configuration; the device is reconnected by name on
the next launch (and flagged if it isn't plugged in).

!!! note
    If visual stimulation reports that no BlinkStick is set, open the **Devices**
    window and bind one to the **Bedroom lights** role (plug it in first; use
    **File ▸ Refresh devices** or `F5` if it isn't listed). No restart needed.

## More devices

Support for additional hardware is planned — for example a
[Philips Hue](https://github.com/remrama/smacc/issues/53) bridge for ambient room
lighting. This page will grow as devices are added.

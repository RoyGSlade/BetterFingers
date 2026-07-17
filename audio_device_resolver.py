"""Stable microphone identification across PortAudio index churn.

PortAudio device indices are positional, not stable identifiers: they can
change after a reboot, a USB unplug/replug, adding another audio device, a
driver update, or a host-API change. Profiles therefore store a *fingerprint*
of the chosen microphone (host API name, device name, input channel count,
default sample rate, plus the last-known index as a hint) and resolve it to
the device's current index at recording start.
"""

import logging

FINGERPRINT_KEYS = (
    "name",
    "host_api",
    "max_input_channels",
    "default_samplerate",
    "last_known_index",
)


def _query_devices():
    """Snapshot the current PortAudio device table with host-API names attached."""
    import sounddevice as sd

    hostapis = list(sd.query_hostapis())
    devices = []
    for idx, dev in enumerate(sd.query_devices()):
        api_idx = int(dev.get("hostapi", -1))
        api_name = ""
        if 0 <= api_idx < len(hostapis):
            api_name = str(hostapis[api_idx].get("name", ""))
        devices.append({
            "index": idx,
            "name": str(dev.get("name", "")),
            "host_api": api_name,
            "max_input_channels": int(dev.get("max_input_channels", 0)),
            "default_samplerate": float(dev.get("default_samplerate", 0.0)),
        })
    return devices


def build_input_device_fingerprint(index):
    """Fingerprint the input device currently sitting at `index`.

    Returns None when the device can't be fingerprinted (index out of range,
    output-only device, or PortAudio unavailable), so callers keep whatever
    they already had rather than storing garbage.
    """
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        return None
    try:
        devices = _query_devices()
    except Exception as exc:
        logging.warning(f"Could not fingerprint input device {index}: {exc}")
        return None
    if index >= len(devices):
        return None
    dev = devices[index]
    if dev["max_input_channels"] <= 0 or not dev["name"]:
        return None
    return {
        "name": dev["name"],
        "host_api": dev["host_api"],
        "max_input_channels": dev["max_input_channels"],
        "default_samplerate": dev["default_samplerate"],
        "last_known_index": index,
    }


def _matches(dev, fingerprint, require_host_api=True, require_channels=True):
    if dev["max_input_channels"] <= 0:
        return False
    if dev["name"] != fingerprint.get("name"):
        return False
    if require_host_api and dev["host_api"] != fingerprint.get("host_api"):
        return False
    if require_channels and dev["max_input_channels"] != fingerprint.get("max_input_channels"):
        return False
    return True


def resolve_input_device(fingerprint):
    """Resolve a stored fingerprint to the microphone's current PortAudio index.

    The stored index is only a hint: it is trusted when the device sitting at
    it still matches the fingerprint. Otherwise the device table is scanned
    with progressively relaxed criteria (name + host API + channel count →
    name + host API → name alone) so a driver update that changes the channel
    count, or a host-API switch, still finds the same physical microphone.
    Returns None when the microphone is gone.
    """
    if not isinstance(fingerprint, dict) or not fingerprint.get("name"):
        return None
    try:
        devices = _query_devices()
    except Exception as exc:
        logging.warning(f"Input device resolution failed: {exc}")
        return None

    hint = fingerprint.get("last_known_index")
    if (
        isinstance(hint, int)
        and not isinstance(hint, bool)
        and 0 <= hint < len(devices)
        and _matches(devices[hint], fingerprint)
    ):
        return hint

    for require_host_api, require_channels in ((True, True), (True, False), (False, False)):
        for dev in devices:
            if _matches(dev, fingerprint, require_host_api, require_channels):
                return dev["index"]
    return None

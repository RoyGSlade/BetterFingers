import logging
import threading
import time
from ctypes import POINTER, cast

try:
    import comtypes
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    CORE_AUDIO_AVAILABLE = True
except Exception as exc:
    CORE_AUDIO_AVAILABLE = False
    CORE_AUDIO_IMPORT_ERROR = exc

class AudioDucker:
    """
    Windows master-volume ducker.
    Reads current volume, applies a lower level while recording, then restores the prior level.
    """

    def __init__(self):
        self.available = CORE_AUDIO_AVAILABLE
        self._lock = threading.Lock()
        self._ducked = False
        self._pre_duck_volume = None
        self._pre_duck_mute = None
        self._fallback_restore_level = 1.0

        if not self.available:
            logging.warning(f"Core audio ducking unavailable: {CORE_AUDIO_IMPORT_ERROR}")

    @staticmethod
    def _clamp_level(level, default=1.0):
        try:
            value = float(level)
        except Exception:
            value = float(default)
        return max(0.0, min(1.0, value))

    def _get_endpoint(self):
        devices = AudioUtilities.GetSpeakers()
        endpoint = getattr(devices, "EndpointVolume", None)
        if endpoint is not None:
            return endpoint

        activate = getattr(devices, "Activate", None)
        if activate is None:
            activate = getattr(devices, "activate", None)
        if activate is None:
            raise RuntimeError("Could not access endpoint activation API.")

        interface = activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))

    def _read_audio_state(self):
        if not self.available:
            return None

        coinited = False
        try:
            comtypes.CoInitialize()
            coinited = True
            endpoint = self._get_endpoint()
            return float(endpoint.GetMasterVolumeLevelScalar()), bool(endpoint.GetMute())
        except Exception as exc:
            logging.error(f"Failed to read system audio state: {exc}")
            return None
        finally:
            if coinited:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def _set_audio_state(self, level=None, muted=None):
        if not self.available:
            return False

        coinited = False
        try:
            comtypes.CoInitialize()
            coinited = True
            endpoint = self._get_endpoint()
            if level is not None:
                endpoint.SetMasterVolumeLevelScalar(self._clamp_level(level), None)
            if muted is not None:
                endpoint.SetMute(1 if muted else 0, None)
            return True
        except Exception as exc:
            logging.error(f"Failed to set system audio state: {exc}")
            return False
        finally:
            if coinited:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def _fade_volume(self, start_vol, end_vol, duration_s=0.2, steps=10):
        if not self.available:
            return False

        coinited = False
        try:
            comtypes.CoInitialize()
            coinited = True
            endpoint = self._get_endpoint()
            
            diff = end_vol - start_vol
            if abs(diff) < 0.01:
                endpoint.SetMasterVolumeLevelScalar(end_vol, None)
                return True
                
            step_delay = duration_s / steps
            for i in range(1, steps + 1):
                fraction = i / steps
                current_vol = start_vol + (diff * fraction)
                endpoint.SetMasterVolumeLevelScalar(self._clamp_level(current_vol), None)
                time.sleep(step_delay)
            
            return True
        except Exception as exc:
            logging.error(f"Failed to fade audio: {exc}")
            return False
        finally:
            if coinited:
                try:
                    comtypes.CoUninitialize()
                except Exception:
                    pass

    def duck(self, target_level=0.18, fallback_restore_level=1.0, fade_duration=0.2):
        """Reduce master output volume to target_level (0.0-1.0)."""
        del fade_duration
        target = self._clamp_level(target_level, default=0.18)
        fallback = self._clamp_level(fallback_restore_level, default=1.0)
        with self._lock:
            if self._ducked:
                return

            self._fallback_restore_level = fallback
            prior_state = self._read_audio_state()
            current_vol = 1.0
            if prior_state is not None:
                self._pre_duck_volume, self._pre_duck_mute = prior_state
                current_vol = self._pre_duck_volume
            else:
                self._pre_duck_volume, self._pre_duck_mute = None, None

            if self._set_audio_state(level=target, muted=None):
                self._ducked = True

    def unduck(self, fade_duration=0.2):
        """Restore master output volume to pre-duck level or fallback."""
        del fade_duration
        with self._lock:
            if not self._ducked:
                return

            restore_level = self._pre_duck_volume
            if restore_level is None:
                restore_level = self._fallback_restore_level
            
            restored = self._set_audio_state(level=restore_level, muted=self._pre_duck_mute)

            if not restored:
                logging.error("Failed to restore audio after ducking.")

            self._ducked = False
            self._pre_duck_volume = None
            self._pre_duck_mute = None

    # Aliases
    def duck_volume(self, target_level=0.18, fallback_restore_level=1.0, fade_duration=0.2):
        return self.duck(target_level, fallback_restore_level, fade_duration)

    def restore_volume(self):
        return self.unduck(fade_duration=0.2)

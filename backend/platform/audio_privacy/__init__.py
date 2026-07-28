"""Input voice privacy: capture isolation adapters and the journaled lease.

D-0010 splits output ducking from input voice privacy and requires the input
half to use a **lease-based, journaled, exact restoration** lifecycle. This
package is that half:

* :mod:`~backend.platform.audio_privacy.base` — the adapter contract, the
  result vocabulary, and runtime detection. No platform code.
* :mod:`~backend.platform.audio_privacy.journal` — the crash-recovery
  journal, written before any state change, content-free, recovered and
  cleared at startup.
* :mod:`~backend.platform.audio_privacy.linux_pulse` — PulseAudio / PipeWire
  capture isolation via structured ``pactl`` output. Never name matching.
* :mod:`~backend.platform.audio_privacy.windows_core_audio` — a documented
  feasibility design that stays unavailable until a Core Audio spike passes;
  Windows uses push-to-mute.
* :mod:`~backend.platform.audio_privacy.lease` — the one owner of
  engage/release, driving both mechanisms and producing the real
  ``restore_complete`` that :func:`audio_status.voice_privacy_status` reports
  through.

Import the module you need::

    from backend.platform.audio_privacy import lease
    lease.get_lease().acquire(config, reason="wake_word")

This ``__init__`` deliberately re-exports **nothing**. Every module in the
package imports its siblings absolutely (``from backend.platform.audio_privacy
.base import ...``), matching the rest of ``backend/``; a re-exporting
``__init__`` would make the package module a dependency of its own leaves and
show up as an import cycle in ``tests/test_architecture_smoke.py``. Keeping it
empty is what makes the dependency graph the DAG it actually is:
``lease → journal → base``.
"""

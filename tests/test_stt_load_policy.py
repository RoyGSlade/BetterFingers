"""STT load policy: adaptive CPU thread count + load-time CUDA inference probe.

No real Whisper model is ever loaded: ``transcriber.WhisperModel`` is replaced
by a recording fake that can be told to raise from ``transcribe``.
"""
import gc
import os
import types
import unittest
import weakref
from unittest.mock import patch

import numpy as np

from backend.stt import transcriber as stt
from backend.stt.transcriber import (
    STT_CPU_THREAD_CAP,
    Transcriber,
    choose_stt_cpu_threads,
    classify_cuda_runtime_error,
)

CUBLAS_MSG = "Library cublas64_12.dll is not found or cannot be loaded"
ENV_KEY = "BETTERFINGERS_STT_CPU_THREADS"


class _Segment:
    start = 0.0
    end = 0.5
    text = "load policy test phrase"


def make_fake_whisper(
    *,
    cuda_error=None,
    cpu_error=None,
    healthy_cuda_calls=0,
    cuda_construct_failures=0,
    cuda_construct_error=None,
    lazy=True,
):
    """Build a recording stand-in for ``faster_whisper.WhisperModel``.

    ``state.attempts``  kwargs of every constructor call, failed ones included.
    ``state.log``       (device, audio shape, audio dtype, kwargs) per transcribe call.
    ``state.refs``      (device, weakref) per successfully built model.
    ``cuda_error``      raised from CUDA ``transcribe`` once ``healthy_cuda_calls``
                        calls have gone by (the load-time probe is call number 1).
    ``lazy``            raise while iterating the segments (like the real lazy
                        generator) instead of at the ``transcribe()`` call.
    """
    state = types.SimpleNamespace(
        attempts=[],
        log=[],
        refs=[],
        construct_failures_left=cuda_construct_failures,
    )

    class FakeWhisperModel:
        def __init__(self, model_size, **kwargs):
            state.attempts.append(dict(kwargs))
            device = kwargs.get("device")
            if device == "cuda" and state.construct_failures_left > 0:
                state.construct_failures_left -= 1
                raise cuda_construct_error or RuntimeError("model cache is corrupt")
            self.model_size = model_size
            self.kwargs = dict(kwargs)
            self.device = device
            self.calls = 0
            state.refs.append((device, weakref.ref(self)))

        def transcribe(self, audio, **kwargs):
            self.calls += 1
            state.log.append((self.device, audio.shape, audio.dtype, dict(kwargs)))
            error = cpu_error if self.device == "cpu" else cuda_error
            failing = error is not None and (
                self.device == "cpu" or self.calls > healthy_cuda_calls
            )
            if failing and not lazy:
                raise error

            def segments():
                if failing:
                    raise error
                yield _Segment()

            return segments(), None

    FakeWhisperModel.state = state
    return FakeWhisperModel


def make_fake_psutil(*, cpu_percent=0.0, cpu_count=12, percent_error=None, count_error=None):
    def _cpu_percent(interval=None):
        del interval
        if percent_error is not None:
            raise percent_error
        return cpu_percent

    def _cpu_count(logical=True):
        if count_error is not None:
            raise count_error
        return cpu_count if not logical else (cpu_count or 0) * 2

    return types.SimpleNamespace(cpu_percent=_cpu_percent, cpu_count=_cpu_count)


class ChooseThreadsPolicyTests(unittest.TestCase):
    def _choose(self, physical, load, env=None):
        return choose_stt_cpu_threads(
            physical_cores=physical,
            cpu_load_percent=load,
            env={} if env is None else env,
        )

    def test_cap_is_the_measured_knee(self):
        self.assertEqual(STT_CPU_THREAD_CAP, 8)

    def test_policy_table(self):
        cases = [
            # physical, load %, expected
            (12, 0, 8),
            (12, 10, 8),
            (12, 50, 6),
            (12, 100, 2),
            (4, 0, 4),
            (6, 0, 6),
            (2, 100, 2),
            (1, 0, 1),
            (1, 100, 1),
        ]
        for physical, load, expected in cases:
            with self.subTest(physical=physical, load=load):
                self.assertEqual(self._choose(physical, load), expected)

    def test_never_above_physical_cores_or_cap(self):
        for physical in range(1, 33):
            for load in (0, 25, 50, 75, 100):
                with self.subTest(physical=physical, load=load):
                    threads = self._choose(physical, load)
                    self.assertLessEqual(threads, min(physical, STT_CPU_THREAD_CAP))
                    self.assertGreaterEqual(threads, min(2, physical))

    def test_load_is_clamped_to_0_100(self):
        self.assertEqual(self._choose(12, 250), 2)
        self.assertEqual(self._choose(6, -20), 6)

    def test_env_override_wins_over_policy(self):
        self.assertEqual(self._choose(12, 100, env={ENV_KEY: "5"}), 5)
        self.assertEqual(self._choose(12, 0, env={ENV_KEY: " 5 "}), 5)

    def test_env_override_is_read_from_os_environ_by_default(self):
        with patch.dict(os.environ, {ENV_KEY: "5"}):
            self.assertEqual(
                choose_stt_cpu_threads(physical_cores=12, cpu_load_percent=100),
                5,
            )

    def test_invalid_env_override_is_ignored(self):
        for bad in ("abc", "0", "-3", "", "5.5"):
            with self.subTest(value=bad):
                self.assertEqual(self._choose(12, 0, env={ENV_KEY: bad}), 8)
                self.assertEqual(self._choose(6, 50, env={ENV_KEY: bad}), 3)

    def test_psutil_load_failure_counts_as_idle(self):
        broken = make_fake_psutil(percent_error=OSError("psutil exploded"))
        with patch.object(stt, "psutil", broken):
            # 0% load on 6 physical cores -> 6. Treating the failure as busy would give 2.
            self.assertEqual(choose_stt_cpu_threads(physical_cores=6, env={}), 6)

    def test_missing_psutil_counts_as_idle(self):
        with patch.object(stt, "psutil", None):
            self.assertEqual(choose_stt_cpu_threads(physical_cores=6, env={}), 6)

    def test_load_is_sampled_from_psutil_when_not_given(self):
        with patch.object(stt, "psutil", make_fake_psutil(cpu_percent=50.0)):
            self.assertEqual(choose_stt_cpu_threads(physical_cores=12, env={}), 6)

    def test_physical_cores_come_from_psutil_when_not_given(self):
        with patch.object(stt, "psutil", make_fake_psutil(cpu_percent=0.0, cpu_count=6)):
            self.assertEqual(choose_stt_cpu_threads(env={}), 6)

    def test_physical_cores_fall_back_to_half_of_logical_when_psutil_cannot_say(self):
        with patch.object(stt, "psutil", make_fake_psutil(count_error=OSError("nope"))), \
             patch("backend.stt.transcriber.os.cpu_count", return_value=8):
            self.assertEqual(choose_stt_cpu_threads(cpu_load_percent=0, env={}), 4)


class _LoadTestCase(unittest.TestCase):
    def _transcriber(self, fake, *, prefer_gpu, model_size="base.en", cached=True):
        self.load_profile = patch(
            "backend.stt.transcriber.load_profile",
            return_value={"model_size": model_size, "use_gpu": prefer_gpu},
        ).start()
        self.addCleanup(patch.stopall)
        patch.object(Transcriber, "_is_model_cached", return_value=cached).start()
        patch("backend.stt.transcriber.WhisperModel", new=fake).start()
        return Transcriber(profile_name="Default", preload=False)

    @staticmethod
    def _devices(fake):
        return [attempt["device"] for attempt in fake.state.attempts]


class CpuLoadThreadsTests(_LoadTestCase):
    def test_cpu_load_passes_policy_threads_and_records_them(self):
        fake = make_fake_whisper()
        t = self._transcriber(fake, prefer_gpu=False)

        with patch("backend.stt.transcriber.choose_stt_cpu_threads", return_value=5) as choose:
            self.assertTrue(t.ensure_loaded())

        choose.assert_called_once()
        self.assertEqual(self._devices(fake), ["cpu"])
        self.assertEqual(fake.state.attempts[0]["cpu_threads"], 5)
        self.assertEqual(t.active_device, "cpu")
        self.assertEqual(t.active_cpu_threads, 5)
        self.assertEqual(t.get_runtime_status()["active_cpu_threads"], 5)

    def test_cpu_load_uses_measured_inputs_end_to_end_and_logs_once(self):
        fake = make_fake_whisper()
        t = self._transcriber(fake, prefer_gpu=False)
        env = {k: v for k, v in os.environ.items() if k != ENV_KEY}

        with patch.dict(os.environ, env, clear=True), \
             patch("backend.stt.transcriber._detect_physical_cores", return_value=12), \
             patch("backend.stt.transcriber._sample_cpu_load_percent", return_value=50.0), \
             self.assertLogs(level="INFO") as logs:
            self.assertTrue(t.ensure_loaded())

        self.assertEqual(fake.state.attempts[0]["cpu_threads"], 6)
        self.assertEqual(t.active_cpu_threads, 6)
        thread_lines = [m for m in logs.output if "Whisper CPU threads:" in m]
        self.assertEqual(len(thread_lines), 1)
        self.assertIn("Whisper CPU threads: 6 (physical=12, load=50%)", thread_lines[0])

    def test_cpu_cache_retry_construction_passes_threads_too(self):
        # First CPU construction (local cache) fails, the remote-fetch retry succeeds.
        fake = make_fake_whisper()
        real_init = fake.__init__
        failures = {"left": 1}

        def flaky_init(self, model_size, **kwargs):
            if kwargs.get("device") == "cpu" and failures["left"] > 0:
                failures["left"] -= 1
                fake.state.attempts.append(dict(kwargs))
                raise RuntimeError("local cache is corrupt")
            real_init(self, model_size, **kwargs)

        fake.__init__ = flaky_init
        t = self._transcriber(fake, prefer_gpu=False)

        with patch("backend.stt.transcriber.choose_stt_cpu_threads", return_value=4) as choose:
            self.assertTrue(t.ensure_loaded())

        choose.assert_called_once()  # one policy decision (and one log line) per load
        self.assertEqual(len(fake.state.attempts), 2)
        self.assertEqual([a["cpu_threads"] for a in fake.state.attempts], [4, 4])
        self.assertTrue(fake.state.attempts[0]["local_files_only"])
        self.assertFalse(fake.state.attempts[1]["local_files_only"])
        self.assertEqual(t.active_cpu_threads, 4)

    def test_cpu_fallback_model_passes_threads(self):
        fake = make_fake_whisper()
        t = self._transcriber(fake, prefer_gpu=True)

        with patch("backend.stt.transcriber.choose_stt_cpu_threads", return_value=3):
            model = t._load_cpu_fallback_model()

        self.assertEqual(model.kwargs["device"], "cpu")
        self.assertEqual(model.kwargs["cpu_threads"], 3)
        self.assertEqual(t.active_device, "cpu")
        self.assertEqual(t.active_cpu_threads, 3)

    def test_active_cpu_threads_resets_with_active_device(self):
        fake = make_fake_whisper()
        t = self._transcriber(fake, prefer_gpu=False)
        self.assertIsNone(t.active_cpu_threads)  # initialised while unloaded

        with patch("backend.stt.transcriber.choose_stt_cpu_threads", return_value=5):
            t.ensure_loaded()
        self.assertEqual(t.active_cpu_threads, 5)

        t.unload()
        self.assertIsNone(t.active_device)
        self.assertIsNone(t.active_cpu_threads)

        with patch("backend.stt.transcriber.choose_stt_cpu_threads", return_value=5):
            t.ensure_loaded()
        self.assertEqual(t.active_cpu_threads, 5)

        self.load_profile.return_value = {"model_size": "small.en", "use_gpu": False}
        t.reload_profile(profile_name="Default", preload=False)
        self.assertIsNone(t.model)
        self.assertIsNone(t.active_device)
        self.assertIsNone(t.active_cpu_threads)


class CudaLoadProbeTests(_LoadTestCase):
    def test_probe_failure_falls_back_to_cpu_at_load_time(self):
        error = RuntimeError(CUBLAS_MSG)
        expected_code = classify_cuda_runtime_error(error)
        self.assertIsNotNone(expected_code)

        for lazy in (True, False):
            with self.subTest(lazy=lazy):
                patch.stopall()
                fake = make_fake_whisper(cuda_error=error, lazy=lazy)
                t = self._transcriber(fake, prefer_gpu=True)
                events = []
                t.set_error_reporter(events.append)

                with patch("backend.stt.transcriber.choose_stt_cpu_threads", return_value=5):
                    self.assertTrue(t.ensure_loaded())

                self.assertEqual(self._devices(fake), ["cuda", "cpu"])
                self.assertEqual(t.model.kwargs["device"], "cpu")
                self.assertEqual(t.model.kwargs["cpu_threads"], 5)
                self.assertEqual(t.active_device, "cpu")
                self.assertEqual(t.active_compute_type, "int8")
                self.assertEqual(t.active_cpu_threads, 5)
                self.assertEqual(t.device_fallback_code, expected_code)
                self.assertEqual(t.device_fallback_reason, "CUDA inference probe failed")
                # The probe was the minimal real inference, and only the CUDA model ran it.
                self.assertEqual(
                    fake.state.log,
                    [("cuda", (16000,), np.dtype("float32"),
                      {"beam_size": 1, "without_timestamps": True})],
                )
                # The unproven CPU model has not decoded anything yet.
                status = t.get_runtime_status()
                self.assertFalse(status["inference_ready"])
                self.assertFalse(status["probe_passed"])
                self.assertEqual(events[-1]["code"], expected_code)
                self.assertEqual(events[-1]["state"], "fallback_active")
                self.assertTrue(events[-1]["fallback"])
                self.assertEqual(events[-1]["active_cpu_threads"], 5)

    def test_probe_failure_releases_the_cuda_model(self):
        fake = make_fake_whisper(cuda_error=RuntimeError(CUBLAS_MSG))
        t = self._transcriber(fake, prefer_gpu=True)

        self.assertTrue(t.ensure_loaded())
        gc.collect()

        cuda_refs = [ref for device, ref in fake.state.refs if device == "cuda"]
        self.assertEqual(len(cuda_refs), 1)
        self.assertIsNone(cuda_refs[0]())

    def test_unrecognized_probe_error_still_falls_back_without_inventing_a_code(self):
        error = ValueError("user said something private")
        self.assertIsNone(classify_cuda_runtime_error(error))
        fake = make_fake_whisper(cuda_error=error)
        t = self._transcriber(fake, prefer_gpu=True)

        self.assertTrue(t.ensure_loaded())

        self.assertEqual(self._devices(fake), ["cuda", "cpu"])
        self.assertEqual(t.active_device, "cpu")
        self.assertIsNotNone(t.active_cpu_threads)
        self.assertIsNone(t.device_fallback_code)
        self.assertEqual(t.device_fallback_reason, "CUDA inference probe failed (ValueError)")
        self.assertNotIn("private", t.device_fallback_reason)

    def test_probe_pass_keeps_cuda_and_changes_nothing_else(self):
        fake = make_fake_whisper()
        t = self._transcriber(fake, prefer_gpu=True)

        self.assertTrue(t.ensure_loaded())

        self.assertEqual(self._devices(fake), ["cuda"])  # no CPU construction
        self.assertNotIn("cpu_threads", fake.state.attempts[0])
        self.assertEqual(t.active_device, "cuda")
        self.assertEqual(t.active_compute_type, "float16")
        self.assertIsNone(t.active_cpu_threads)
        self.assertIsNone(t.device_fallback_reason)
        self.assertIsNone(t.device_fallback_code)
        self.assertEqual(len(fake.state.log), 1)  # just the probe
        status = t.get_runtime_status()
        self.assertIsNone(status["active_cpu_threads"])

    def test_probe_pass_marks_inference_ready_but_not_probe_passed(self):
        fake = make_fake_whisper()
        t = self._transcriber(fake, prefer_gpu=True)

        t.ensure_loaded()
        status = t.get_runtime_status()

        # A real CUDA decode already succeeded at load time; runtime_probe() still owns probe_passed.
        self.assertTrue(status["inference_ready"])
        self.assertFalse(status["probe_passed"])

        t.unload()
        self.assertFalse(t.get_runtime_status()["inference_ready"])

    def test_cache_refresh_retry_is_probed_too(self):
        fake = make_fake_whisper(
            cuda_error=RuntimeError(CUBLAS_MSG),
            cuda_construct_failures=1,
        )
        t = self._transcriber(fake, prefer_gpu=True, cached=True)

        self.assertTrue(t.ensure_loaded())

        # cuda (local cache, constructor fails) -> cuda (remote retry, constructs) -> probe fails -> cpu
        self.assertEqual(self._devices(fake), ["cuda", "cuda", "cpu"])
        self.assertTrue(fake.state.attempts[0]["local_files_only"])
        self.assertFalse(fake.state.attempts[1]["local_files_only"])
        self.assertEqual(len(fake.state.log), 1)
        self.assertEqual(t.active_device, "cpu")
        self.assertEqual(t.device_fallback_code, classify_cuda_runtime_error(RuntimeError(CUBLAS_MSG)))
        self.assertEqual(t.device_fallback_reason, "CUDA inference probe failed")

    def test_cache_refresh_retry_that_passes_its_probe_stays_on_cuda(self):
        fake = make_fake_whisper(cuda_construct_failures=1)
        t = self._transcriber(fake, prefer_gpu=True, cached=True)

        self.assertTrue(t.ensure_loaded())

        self.assertEqual(self._devices(fake), ["cuda", "cuda"])
        self.assertEqual(t.active_device, "cuda")
        self.assertIsNone(t.active_cpu_threads)
        self.assertEqual(len(fake.state.log), 1)

    def test_probe_failure_does_not_trigger_the_cache_refresh_retry(self):
        # The constructor worked from the local cache, so a probe failure is not a cache problem.
        fake = make_fake_whisper(cuda_error=RuntimeError(CUBLAS_MSG))
        t = self._transcriber(fake, prefer_gpu=True, cached=True)

        t.ensure_loaded()

        self.assertEqual(self._devices(fake), ["cuda", "cpu"])

    def test_unclassifiable_cuda_construction_failure_still_fails_the_load(self):
        fake = make_fake_whisper(
            cuda_construct_failures=2,
            cuda_construct_error=ValueError("not a CUDA runtime problem"),
        )
        t = self._transcriber(fake, prefer_gpu=True, cached=True)

        self.assertFalse(t.ensure_loaded())

        self.assertEqual(self._devices(fake), ["cuda", "cuda"])  # no silent CPU build
        self.assertIsNone(t.model)
        self.assertIsNone(t.active_device)
        self.assertIsNone(t.active_cpu_threads)

    def test_lazy_recovery_backstop_still_works_after_a_passing_probe(self):
        # The load-time probe passes (call 1), then a later decode fails -> existing lazy recovery.
        fake = make_fake_whisper(cuda_error=RuntimeError(CUBLAS_MSG), healthy_cuda_calls=1)
        t = self._transcriber(fake, prefer_gpu=True)

        with patch("backend.stt.transcriber.choose_stt_cpu_threads", return_value=4):
            result = t.transcribe(np.zeros(1600, dtype=np.float32))

        self.assertEqual(result, "load policy test phrase")
        self.assertEqual(self._devices(fake), ["cuda", "cpu"])
        self.assertEqual(fake.state.attempts[1]["cpu_threads"], 4)
        self.assertEqual(t.active_device, "cpu")
        self.assertEqual(t.active_cpu_threads, 4)
        self.assertEqual(t.device_fallback_code, "cuda_runtime_missing")


class CudaFailureMemoTests(_LoadTestCase):
    """Once CUDA failed in this process, later loads must not touch CUDA again.

    A second CUDA decode after a failed cuBLAS load hung inside CTranslate2 on a
    real RTX 5070 laptop (while holding the model lock), so retrying is unsafe.
    """

    def test_reload_after_probe_failure_skips_cuda(self):
        error = RuntimeError(CUBLAS_MSG)
        fake = make_fake_whisper(cuda_error=error)
        t = self._transcriber(fake, prefer_gpu=True)
        self.assertTrue(t.ensure_loaded())
        self.assertEqual(self._devices(fake), ["cuda", "cpu"])

        t.unload()
        self.assertTrue(t.ensure_loaded())

        self.assertEqual(self._devices(fake), ["cuda", "cpu", "cpu"])
        self.assertEqual(t.active_device, "cpu")
        self.assertEqual(t.device_fallback_code, classify_cuda_runtime_error(error))
        self.assertEqual(t.device_fallback_reason, "CUDA inference probe failed")

    def test_lazy_decode_failure_is_remembered_too(self):
        fake = make_fake_whisper(cuda_error=RuntimeError(CUBLAS_MSG), healthy_cuda_calls=1)
        t = self._transcriber(fake, prefer_gpu=True)
        self.assertTrue(t.ensure_loaded())  # the load-time probe passes
        t.transcribe(np.zeros(1600, dtype=np.float32))  # the real decode fails -> CPU
        self.assertEqual(self._devices(fake), ["cuda", "cpu"])

        t.unload()
        self.assertTrue(t.ensure_loaded())

        self.assertEqual(self._devices(fake), ["cuda", "cpu", "cpu"])

    def test_memo_is_per_whisper_backend(self):
        failing = make_fake_whisper(cuda_error=RuntimeError(CUBLAS_MSG))
        self.assertTrue(self._transcriber(failing, prefer_gpu=True).ensure_loaded())
        patch.stopall()

        healthy = make_fake_whisper()
        t = self._transcriber(healthy, prefer_gpu=True)
        self.assertTrue(t.ensure_loaded())

        self.assertEqual(self._devices(healthy), ["cuda"])
        self.assertEqual(t.active_device, "cuda")


if __name__ == "__main__":
    unittest.main()

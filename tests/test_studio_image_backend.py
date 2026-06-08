"""Tests for the in-process Diffusers image backend (MEDIA_DISPATCHER §4.4).

These exercise the pure mapping/availability logic — no model is ever loaded, so they run with or
without `diffusers` installed.
"""

import studio_image_backend as B


def _packet():
    return {"positive_prompt": "a cold harbor", "negative_prompt": "blurry",
            "steps": 30, "cfg": 7.0, "width": 1024, "height": 576, "seed": 42,
            "sampler": "dpmpp_2m", "scheduler": "karras", "model": "sdxl_anime"}


def test_packet_to_kwargs_maps_fields():
    k = B.packet_to_kwargs(_packet())
    assert k["prompt"] == "a cold harbor"
    assert k["negative_prompt"] == "blurry"
    assert k["num_inference_steps"] == 30
    assert k["guidance_scale"] == 7.0
    assert k["width"] == 1024 and k["height"] == 576
    # generator is added at render time (needs a torch device), not here
    assert "generator" not in k


def test_packet_to_kwargs_defaults_on_empty():
    k = B.packet_to_kwargs({})
    assert k["num_inference_steps"] == 24 and k["guidance_scale"] == 6.5
    assert k["width"] == 768 and k["height"] == 768


def test_scheduler_resolution():
    assert B.resolve_scheduler_name("dpmpp_2m", "karras") == \
        ("DPMSolverMultistepScheduler", {"use_karras_sigmas": True})
    assert B.resolve_scheduler_name("euler_a", "")[0] == "EulerAncestralDiscreteScheduler"
    # Unknown hint -> safe default.
    assert B.resolve_scheduler_name("totally_unknown", "weird")[0] == "DPMSolverMultistepScheduler"


def test_healthcheck_false_without_model_or_deps():
    be = B.DiffusersBackend(model_path="")        # no model path
    assert be.healthcheck() is False


def test_make_image_backend_off_returns_none():
    assert B.make_image_backend({"image_backend": "off"}) is None
    assert B.make_image_backend({}) is None or callable(B.make_image_backend({}))  # depends on env


def test_make_image_backend_unavailable_is_none_not_crash():
    # diffusers backend pointed at a missing model on a box without the deps -> graceful None.
    fn = B.make_image_backend({"image_backend": "diffusers", "image_model_path": "/nope/missing.safetensors"})
    assert fn is None


def test_start_download_reuses_active_job(monkeypatch):
    calls = []

    class FakeThread:
        def __init__(self, target=None, name=None, daemon=None):
            self.target = target
            self.name = name
            self.daemon = daemon
            self.started = False

        def start(self):
            self.started = True
            calls.append(self)

        def is_alive(self):
            return self.started

    monkeypatch.setattr(B, "_DL_STATE", {})
    monkeypatch.setattr(B, "_DL_THREADS", {})
    monkeypatch.setattr(B, "image_model_installed", lambda _key: False)
    monkeypatch.setattr(B.threading, "Thread", FakeThread)

    first = B.start_download("animagine-xl-4")
    second = B.start_download("animagine-xl-4")

    assert first["status"] == "downloading"
    assert second["active"] is True
    assert len(calls) == 1


def test_make_image_backend_saver_unloads_after_render(monkeypatch, tmp_path):
    events = []

    class FakeBackend:
        def __init__(self, *args, **kwargs):
            pass

        def healthcheck(self):
            return True

        def render(self, packet, out_path):
            events.append(("render", packet["positive_prompt"]))
            tmp_path.joinpath("out.png").write_bytes(b"png")
            return True

        def unload(self):
            events.append(("unload", ""))

    monkeypatch.setattr(B, "DiffusersBackend", FakeBackend)
    fn = B.make_image_backend({"image_backend": "diffusers", "image_model_path": str(tmp_path)})

    assert callable(fn)
    assert fn({"positive_prompt": "harbor"}, str(tmp_path / "out.png")) is True
    assert events == [("render", "harbor"), ("unload", "")]

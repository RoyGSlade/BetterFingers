"""Bounded, signature-checked uploads (P1 upload safety).

stream_to_file caps bytes (413), validate_signature rejects by magic bytes
(not extension), WAV duration and image pixels are bounded, and the routes
clean up temp files and return the right status codes.
"""

import io
import os
import struct
import tempfile
import unittest
import wave

from fastapi.testclient import TestClient

import server
import upload_safety as us


def _wav_bytes(seconds=0.1, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _png_bytes(w=4, h=4):
    try:
        from PIL import Image
    except ImportError:
        return None
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


class StreamCapTests(unittest.TestCase):
    def test_stream_writes_small_file(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "a.bin")
            n = us.stream_to_file(io.BytesIO(b"x" * 100), dest, max_bytes=1000)
            self.assertEqual(n, 100)
            self.assertTrue(os.path.exists(dest))

    def test_stream_aborts_and_cleans_up_on_overflow(self):
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "a.bin")
            with self.assertRaises(us.UploadTooLarge):
                us.stream_to_file(io.BytesIO(b"x" * 5000), dest, max_bytes=1000)
            self.assertFalse(os.path.exists(dest))  # partial removed


class SignatureTests(unittest.TestCase):
    def test_wav_signature_accepts_real_wav(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(_wav_bytes())
            path = f.name
        try:
            us.validate_signature(path, "audio")  # no raise
        finally:
            os.remove(path)

    def test_wav_signature_rejects_non_wav(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"this is not audio at all")
            path = f.name
        try:
            with self.assertRaises(us.UploadRejected):
                us.validate_signature(path, "audio")
        finally:
            os.remove(path)

    def test_wav_duration_rejects_too_long(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(_wav_bytes(seconds=1.0, rate=16000))
            path = f.name
        try:
            with self.assertRaises(us.UploadRejected):
                us.validate_wav_duration(path, max_seconds=0.5)
            self.assertLess(us.validate_wav_duration(path, max_seconds=10), 2.0)
        finally:
            os.remove(path)

    def test_malformed_wav_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF" + b"\x00" * 4 + b"WAVE" + b"garbage")
            path = f.name
        try:
            with self.assertRaises(us.UploadRejected):
                us.validate_wav_duration(path)
        finally:
            os.remove(path)

    def test_image_signature_rejects_non_image(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"definitely not a png")
            path = f.name
        try:
            with self.assertRaises(us.UploadRejected):
                us.validate_signature(path, "image")
        finally:
            os.remove(path)


class ImageValidationTests(unittest.TestCase):
    def test_valid_small_image_passes(self):
        data = _png_bytes(8, 8)
        if data is None:
            self.skipTest("Pillow not installed")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            self.assertEqual(us.validate_image(path), (8, 8))
        finally:
            os.remove(path)

    def test_oversized_image_rejected(self):
        data = _png_bytes(50, 50)
        if data is None:
            self.skipTest("Pillow not installed")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(data)
            path = f.name
        try:
            with self.assertRaises(us.UploadRejected):
                us.validate_image(path, max_pixels=100)  # 2500px > 100
        finally:
            os.remove(path)


class UploadRouteTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_transcribe_rejects_oversized_audio(self):
        big = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * (60 * 1024 * 1024)
        resp = self.client.post("/transcribe", files={"file": ("a.wav", big, "audio/wav")})
        self.assertEqual(resp.status_code, 413)

    def test_transcribe_rejects_non_wav_content(self):
        resp = self.client.post(
            "/transcribe", files={"file": ("evil.wav", b"nope not audio", "audio/wav")}
        )
        self.assertEqual(resp.status_code, 400)

    def test_ocr_rejects_non_image_content(self):
        resp = self.client.post(
            "/ocr/extract", files={"file": ("evil.png", b"nope not an image", "image/png")}
        )
        self.assertEqual(resp.status_code, 400)

    def test_voice_clone_rejects_non_wav(self):
        resp = self.client.post(
            "/tts/clone",
            data={"name": "Test", "consent": "true"},
            files={"file": ("evil.wav", b"not a wav file", "audio/wav")},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()

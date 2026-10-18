"""Облачное распознавание: формат запроса и обработка ошибок (без сети)."""
import io
import json
import unittest
import urllib.error
from unittest import mock

from jarvis.voice import stt_api


class SttApiTest(unittest.TestCase):
    def test_request_format(self):
        seen = {}

        def fake_urlopen(req, timeout, context):
            seen["url"], seen["auth"], seen["body"] = req.full_url, req.headers["Authorization"], req.data
            return io.BytesIO(json.dumps({"text": " Открой калькулятор "}).encode())

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            text = stt_api.transcribe(b"AUDIO", ".webm", "k123", "groq")
        self.assertEqual(text, "Открой калькулятор")
        self.assertTrue(seen["url"].endswith("/audio/transcriptions"))
        self.assertEqual(seen["auth"], "Bearer k123")
        self.assertIn(b'name="model"\r\n\r\nwhisper-large-v3-turbo', seen["body"])
        self.assertIn(b'name="language"\r\n\r\nru', seen["body"])
        self.assertIn(b"AUDIO", seen["body"])

    def test_bad_key_message(self):
        err = urllib.error.HTTPError("u", 401, "no", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaisesRegex(stt_api.STTApiError, "Ключ API не подошёл"):
                stt_api.transcribe(b"a", ".webm", "bad")

    def test_no_key(self):
        with self.assertRaises(stt_api.STTApiError):
            stt_api.transcribe(b"a", ".webm", "")


if __name__ == "__main__":
    unittest.main()

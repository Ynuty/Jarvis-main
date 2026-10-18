"""Распознавание речи через облачный Whisper API (OpenAI-совместимый
эндпоинт /audio/transcriptions). Не требует установки моделей на устройство.

Внимание: в этом режиме аудио уходит на сервер провайдера — это отход от
принципа «всё локально», поэтому режим включается явно в настройках.
Ключ хранится в хранилище ОС (storage/secrets.py), в коде и в базе его нет.
"""
from __future__ import annotations

import functools
import json
import mimetypes
import secrets
import ssl
import subprocess
import sys
import urllib.error
import urllib.request

# Только бесплатные варианты. Groq: бесплатный тариф без карты —
# 20 запросов/мин, 2000/сутки, 28 800 секунд аудио в сутки (октябрь 2026).
# При исчерпании лимита API вернёт 429 — сообщаем пользователю.
PROVIDERS: dict[str, dict] = {
    "groq": {"title": "Groq — бесплатно", "url": "https://api.groq.com/openai/v1",
             "model": "whisper-large-v3-turbo"},
}
SECRET_NAME = "stt_api_key"
TIMEOUT = 30


class STTApiError(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    """Python с python.org на macOS не видит системные сертификаты.
    Порядок: certifi (если есть) → корневые сертификаты macOS → по умолчанию."""
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    if sys.platform == "darwin" and not ctx.get_ca_certs():
        r = subprocess.run(["security", "find-certificate", "-a", "-p",
                            "/System/Library/Keychains/SystemRootCertificates.keychain"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout:
            ctx.load_verify_locations(cadata=r.stdout)
    return ctx


def _multipart(fields: dict[str, str], file_field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = "----jarvis" + secrets.token_hex(12)
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
                 f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(audio: bytes, suffix: str, api_key: str, provider: str = "groq") -> str:
    if not api_key:
        raise STTApiError("Не задан ключ API для распознавания — добавьте его в настройках")
    p = PROVIDERS.get(provider, PROVIDERS["groq"])
    body, ctype = _multipart({"model": p["model"], "language": "ru", "response_format": "json"},
                             "file", "speech" + suffix, audio)
    req = urllib.request.Request(p["url"] + "/audio/transcriptions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {api_key}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
            return json.load(r).get("text", "").strip()
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise STTApiError("Ключ API не подошёл — проверьте его в настройках") from e
        if e.code == 429:
            raise STTApiError("Бесплатный лимит Groq на сейчас исчерпан — подождите минуту") from e
        raise STTApiError(f"Сервис распознавания ответил ошибкой {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise STTApiError("Нет связи с сервисом распознавания — проверьте интернет") from e

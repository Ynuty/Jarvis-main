"""Секреты коннекторов. В SQLite лежит только ссылка, сам токен — в хранилище ОС.

Порядок бэкендов: `keyring` (на Windows это Диспетчер учётных данных) →
DPAPI через ctypes (Windows, без зависимостей) → Связка ключей macOS через
утилиту `security` (без зависимостей) → отказ сохранять.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .db import Storage

SERVICE = "Jarvis"


def _keyring():
    try:
        import keyring  # type: ignore
        return keyring
    except ImportError:
        return None


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _crypt(data: bytes, protect: bool) -> bytes:
        crypt32, kernel32 = ctypes.windll.crypt32, ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
        if not fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
            raise OSError("DPAPI: не удалось обработать секрет")
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)


class Secrets:
    def __init__(self, storage: Storage, data_dir: Path):
        self.storage = storage
        self.dir = data_dir / "secrets"

    def put(self, name: str, value: str) -> None:
        kr = _keyring()
        if kr:
            kr.set_password(SERVICE, name, value)
            self.storage.set_secret_ref(name, "keyring", f"{SERVICE}/{name}")
        elif sys.platform == "win32":
            self.dir.mkdir(parents=True, exist_ok=True)
            path = self.dir / f"{name}.bin"
            path.write_bytes(_crypt(value.encode(), protect=True))
            self.storage.set_secret_ref(name, "dpapi", path.name)
        elif sys.platform == "darwin":
            r = subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", name,
                                "-w", value], capture_output=True)
            if r.returncode != 0:
                raise RuntimeError("Не удалось сохранить ключ в Связку ключей")
            self.storage.set_secret_ref(name, "macos-keychain", f"{SERVICE}/{name}")
        else:
            raise RuntimeError("Нет защищённого хранилища: установите пакет keyring")

    def delete(self, name: str) -> None:
        ref = self.storage.get_secret_ref(name)
        if not ref:
            return
        if ref["backend"] == "keyring" and _keyring():
            try:
                _keyring().delete_password(SERVICE, name)
            except Exception:
                pass
        elif ref["backend"] == "dpapi":
            (self.dir / ref["ref"]).unlink(missing_ok=True)
        elif ref["backend"] == "macos-keychain":
            subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", name],
                           capture_output=True)
        self.storage.delete_secret_ref(name)

    def get(self, name: str) -> str | None:
        ref = self.storage.get_secret_ref(name)
        if not ref:
            return None
        if ref["backend"] == "keyring":
            kr = _keyring()
            return kr.get_password(SERVICE, name) if kr else None
        if ref["backend"] == "dpapi" and sys.platform == "win32":
            return _crypt((self.dir / ref["ref"]).read_bytes(), protect=False).decode()
        if ref["backend"] == "macos-keychain":
            r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", name, "-w"],
                               capture_output=True, text=True)
            return r.stdout.strip() if r.returncode == 0 else None
        return None

    @staticmethod
    def mask(value: str) -> str:
        """Для журнала: секрет никогда не пишется целиком."""
        return "••••" + value[-2:] if len(value) > 6 else "••••"

# -*- mode: python ; coding: utf-8 -*-
# Сборка ядра в папку build/core (PyInstaller, onedir). Лёгкий вариант: без CUDA-библиотек NVIDIA —
# Whisper работает на процессоре (если у человека стоит CUDA 12 в системе, подхватится и видеокарта).
# Запуск: scripts/build.ps1
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = SPECPATH + "/.."

datas = [
    (ROOT + "/core/jarvis/llm/prompts", "jarvis/llm/prompts"),
    (ROOT + "/core/jarvis/db/schema.sql", "jarvis/db"),
]
datas += collect_data_files("faster_whisper")          # silero_vad_v6.onnx
datas += collect_data_files("piper")                   # espeak-ng-data
datas += collect_data_files("pymorphy3_dicts_ru")
datas += collect_data_files("pymorphy3")

binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime")

hidden = (collect_submodules("jarvis") + collect_submodules("uvicorn") + collect_submodules("keyring.backends")
          + ["piper.voice", "piper.config", "piper.phonemize_espeak", "win32ctypes.core", "multipart"])

a = Analysis(
    [ROOT + "/scripts/core_entry.py"],
    pathex=[ROOT + "/core"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["nvidia", "torch", "playwright", "tkinter", "matplotlib", "IPython", "pytest", "piper.train",
              "transformers", "peft", "datasets", "trl"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="jarvis-core", console=True,
          icon=ROOT + "/shell/icon.png" if False else None)
coll = COLLECT(exe, a.binaries, a.datas, name="core")

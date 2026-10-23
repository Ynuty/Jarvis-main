"""Точка входа собранного ядра (PyInstaller): то же, что python -m jarvis."""
import multiprocessing

from jarvis.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

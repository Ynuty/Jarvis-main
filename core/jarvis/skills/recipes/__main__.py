"""Самотест рецептов: python -m jarvis.skills.recipes selftest [магазин …]"""
import asyncio
import sys

from . import available


async def main(args: list[str]) -> int:
    from ..order_auto import selftest
    shops = args[1:] if len(args) > 1 else sorted(available())
    bad = 0
    for sid in shops:
        ok, info = await selftest(sid)
        bad += not ok
        print(f"{'OK  ' if ok else 'СЛОМАН'} {sid:12} {info}")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] != "selftest":
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1:])))

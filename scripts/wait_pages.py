#!/usr/bin/env python3
"""
wait_pages.py — чекає, поки сторінка випуску справді відкриється.

Хостинги збирають сайт не миттєво: після коміту минає від кількох секунд
до кількох хвилин. Якщо надіслати повідомлення одразу, читач відкриє
посилання й побачить 404.

Тому цей крок стоїть між збереженням в архів і відправкою: він опитує
адресу сьогоднішнього випуску, поки та не відповість. Першу, що ожила,
записує у state/live-base.txt — саме її бере send.py.

Якщо жодна не ожила за відведений час, файл лишається порожнім, і
повідомлення піде без посилання на повну версію. Краще без посилання,
ніж із неробочим.

Читає:  state/pages.json
Пише:   state/live-base.txt
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
ATTEMPTS = 30          # приблизно 5 хвилин
PAUSE = 10.0
TIMEOUT = 8.0


def candidates():
    """Спершу Cloudflare, якщо налаштований, потім GitHub Pages."""
    out = []
    custom = os.environ.get("PAGES_BASE", "").strip().rstrip("/")
    if custom:
        out.append(custom)
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo and "/" in repo:
        user, name = repo.split("/", 1)
        out.append(f"https://{user}.github.io/{name}")
    return out


def main():
    iso = datetime.now(timezone.utc).date().isoformat()
    p = ROOT / "state" / "pages.json"
    out = ROOT / "state" / "live-base.txt"
    out.parent.mkdir(exist_ok=True)
    out.write_text("", encoding="utf-8")

    if not p.exists():
        print("Немає state/pages.json — сайт не збирався, чекати нічого")
        return
    try:
        slug = json.loads(p.read_text(encoding="utf-8")).get(iso)
    except Exception:
        slug = None
    if not slug:
        print("Немає адреси сьогоднішнього випуску")
        return

    bases = candidates()
    if not bases:
        print("Жодного хостингу не налаштовано")
        return

    print(f"Чекаю сторінку {slug}.html на: " + ", ".join(bases))
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for attempt in range(1, ATTEMPTS + 1):
            for base in bases:
                url = f"{base}/{slug}.html"
                try:
                    r = client.get(url)
                except Exception as exc:
                    if attempt % 6 == 0:
                        print(f"  {base}: {type(exc).__name__}")
                    continue
                if r.status_code < 400:
                    out.write_text(base, encoding="utf-8")
                    print(f"Сторінка доступна за {attempt * PAUSE:.0f} с: {url}")
                    return
                if attempt % 6 == 0:
                    print(f"  {base}: HTTP {r.status_code}")
            time.sleep(PAUSE)

    print(f"За {ATTEMPTS * PAUSE:.0f} с сторінка не з'явилась. "
          "Повідомлення піде без посилання на повну версію.")


if __name__ == "__main__":
    main()

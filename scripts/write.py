#!/usr/bin/env python3
"""
write.py — перетворює дайджест на бріф, веде пам'ять і реєстри прогнозів,
а по неділях додатково готує тижневий огляд.

Читає:  digests/latest.md, prompts/brief.md, prompts/weekly.md,
        state/threads.md, state/predictions.md, state/external.md
Пише:   issues/YYYY-MM-DD.md, issues/latest.md,
        issues/weekly-YYYY-MM-DD.md (по неділях),
        оновлені файли стану
Потрібен секрет: ANTHROPIC_API_KEY

Модель повертає одну відповідь із чотирьох частин, розділених маркерами.
Розбір суворий: якщо маркерів немає, вважаємо весь текст брифом, а стан
не чіпаємо — краще втратити оновлення пам'яті, ніж затерти її сміттям.
"""

import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
VERSION = "2026-08-28.10"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 20000
TIMEOUT = 900.0
ATTEMPTS = 3

MAX_DIGEST_CHARS = 120_000
CAPS = {"threads": 3500, "predictions": 6500, "external": 6500}

STATE = {
    "threads": ROOT / "state" / "threads.md",
    "predictions": ROOT / "state" / "predictions.md",
    "external": ROOT / "state" / "external.md",
}

MARKERS = {
    "brief": "===БРІФ===",
    "threads": "===ПАМЯТЬ===",
    "predictions": "===НАШІ ПРОГНОЗИ===",
    "external": "===ЧУЖІ ПРОГНОЗИ===",
}


def read_state(key):
    p = STATE[key]
    return p.read_text(encoding="utf-8") if p.exists() else ""


def call_api(key, system, user):
    payload = {"model": MODEL, "max_tokens": MAX_TOKENS,
               "system": system, "messages": [{"role": "user", "content": user}]}
    r = None
    for attempt in range(ATTEMPTS):
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                r = client.post("https://api.anthropic.com/v1/messages",
                                headers={"x-api-key": key,
                                         "anthropic-version": "2023-06-01",
                                         "content-type": "application/json"},
                                json=payload)
            break
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            print(f"Спроба {attempt + 1}: {type(exc).__name__}")
            if attempt == ATTEMPTS - 1:
                sys.exit(f"API не відповів за {ATTEMPTS} спроби")
            time.sleep(10 * (attempt + 1))

    if r.status_code in (429, 529) or r.status_code >= 500:
        sys.exit(f"API перевантажений ({r.status_code})")
    if r.status_code >= 400:
        sys.exit(f"API повернув {r.status_code}: {r.text[:400]}")

    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text").strip()
    usage = data.get("usage", {})
    print(f"  вхід {usage.get('input_tokens')} | вихід {usage.get('output_tokens')} "
          f"| зупинка: {data.get('stop_reason')}")
    if data.get("stop_reason") == "max_tokens":
        print("  УВАГА: обірвано лімітом токенів")
    return text


def split_parts(text):
    """Ділить відповідь за маркерами. Без маркерів — усе вважаємо брифом."""
    if MARKERS["brief"] not in text:
        return {"brief": text}, False

    order = ["brief", "threads", "predictions", "external"]
    positions = []
    for key in order:
        i = text.find(MARKERS[key])
        if i >= 0:
            positions.append((i, key))
    positions.sort()

    parts = {}
    for n, (start, key) in enumerate(positions):
        begin = start + len(MARKERS[key])
        end = positions[n + 1][0] if n + 1 < len(positions) else len(text)
        parts[key] = text[begin:end].strip()
    return parts, True


def save_state(parts):
    for key, path in STATE.items():
        body = parts.get(key, "").strip()
        if not body:
            print(f"  {path.name}: модель нічого не повернула, лишаю як було")
            continue
        cap = CAPS[key]
        if len(body) > cap:
            body = body[:cap].rsplit("\n", 1)[0] + "\n[обрізано за розміром]\n"
            print(f"  {path.name}: обрізано до {cap} символів")
        path.write_text(body + "\n", encoding="utf-8")
        print(f"  {path.name}: оновлено ({len(body)} символів)")


def weekly(key, today):
    """Недільний огляд за сімома останніми випусками."""
    issues = sorted((ROOT / "issues").glob("20*-*.md"))
    issues = [p for p in issues if not p.name.startswith("weekly")][-7:]
    if len(issues) < 2:
        print("Тижневий огляд: випусків замало, пропускаю")
        return None

    body = "\n\n".join(f"### Випуск {p.stem}\n{p.read_text(encoding='utf-8')}"
                       for p in issues)
    user = (f"СІМ ОСТАННІХ ВИПУСКІВ:\n\n{body}\n\n"
            f"ПАМ'ЯТЬ:\n{read_state('threads')}\n\n"
            f"НАШІ ПРОГНОЗИ:\n{read_state('predictions')}\n\n"
            f"ЧУЖІ ПРОГНОЗИ:\n{read_state('external')}")

    print(f"Тижневий огляд за {len(issues)} випусками...")
    text = call_api(key, (ROOT / "prompts" / "weekly.md").read_text(encoding="utf-8"), user)
    if not text:
        return None
    path = ROOT / "issues" / f"weekly-{today}.md"
    path.write_text(text + "\n", encoding="utf-8")
    print(f"  збережено: {path.name} ({len(text)} символів)")
    return text


def main():
    print(f"write.py версія {VERSION}")
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Немає секрету ANTHROPIC_API_KEY")

    digest = (ROOT / "digests" / "latest.md").read_text(encoding="utf-8")
    if len(digest) > MAX_DIGEST_CHARS:
        digest = digest[:MAX_DIGEST_CHARS] + "\n\n[дайджест обрізано]"
        print(f"УВАГА: дайджест обрізано до {MAX_DIGEST_CHARS} символів")

    today = datetime.now(timezone.utc).date().isoformat()
    user = (f"ПАМ'ЯТЬ (сюжетні лінії з попередніх днів):\n{read_state('threads')}\n\n"
            f"НАШІ ПРОГНОЗИ:\n{read_state('predictions')}\n\n"
            f"ЧУЖІ ПРОГНОЗИ:\n{read_state('external')}\n\n"
            f"СЬОГОДНІ {today}\n\nДАЙДЖЕСТ:\n{digest}")

    print("Готую випуск...")
    text = call_api(key, (ROOT / "prompts" / "brief.md").read_text(encoding="utf-8"), user)
    if not text:
        sys.exit("API повернув порожню відповідь")

    parts, structured = split_parts(text)
    brief = parts.get("brief", "").strip()
    if not brief:
        sys.exit("У відповіді немає тексту брифу")

    if structured:
        save_state(parts)
    else:
        print("УВАГА: маркерів немає, стан не оновлюю")

    (ROOT / "issues").mkdir(exist_ok=True)
    (ROOT / "issues" / f"{today}.md").write_text(brief + "\n", encoding="utf-8")
    (ROOT / "issues" / "latest.md").write_text(brief + "\n", encoding="utf-8")
    print(f"Бріф: {len(brief)} символів")
    if len(brief) < 3000:
        print("УВАГА: бріф підозріло короткий, очікується 6000-9000")

    # Неділя — додатково тижневий огляд
    if datetime.now(timezone.utc).weekday() == 6:
        weekly(key, today)


if __name__ == "__main__":
    main()

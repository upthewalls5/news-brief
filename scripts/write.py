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

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
VERSION = "2026-08-28.16"
MODEL = "claude-sonnet-5"
MAX_TOKENS = 16000      # на випуск
MAX_TOKENS_STATE = 16000  # на файли стану
TIMEOUT = 1200.0      # загальний бюджет на запит
READ_TIMEOUT = 180.0  # пауза МІЖ частинами потоку, а не на всю відповідь
ATTEMPTS = 3

MAX_DIGEST_CHARS = 120_000
CAPS = {"threads": 3500, "predictions": 6500, "external": 6500,
        "calendar": 2600}

STATE = {
    "threads": ROOT / "state" / "threads.md",
    "predictions": ROOT / "state" / "predictions.md",
    "external": ROOT / "state" / "external.md",
    "calendar": ROOT / "state" / "calendar.md",
}

MARKERS = {
    "greeting": "===ПРИВІТАННЯ===",
    "hook": "===АНОНС===",
    "brief": "===БРІФ===",
    "threads": "===ПАМЯТЬ===",
    "predictions": "===НАШІ ПРОГНОЗИ===",
    "external": "===ЧУЖІ ПРОГНОЗИ===",
    "calendar": "===КАЛЕНДАР===",
}


def read_state(key):
    p = STATE[key]
    return p.read_text(encoding="utf-8") if p.exists() else ""


def stream_once(key, payload):
    """Один потоковий запит. Відповідь приходить частинами, тому з'єднання
    не мовчить чверть години й таймаут по дорозі не спрацьовує."""
    text_parts = []
    usage = {"input": None, "output": None}
    stop = None
    ticks = 0

    headers = {"x-api-key": key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    with httpx.Client(timeout=httpx.Timeout(TIMEOUT, read=READ_TIMEOUT)) as client:
        with client.stream("POST", "https://api.anthropic.com/v1/messages",
                           headers=headers, json={**payload, "stream": True}) as r:
            if r.status_code >= 400:
                r.read()
                return None, r.status_code, r.text[:300], stop, usage

            event = None
            for line in r.iter_lines():
                if not line:
                    continue
                if line.startswith("event: "):
                    event = line[7:].strip()
                    continue
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except Exception:
                    continue

                if event == "content_block_delta":
                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text_parts.append(delta.get("text", ""))
                        ticks += 1
                        if ticks % 400 == 0:
                            print(f"    …{sum(len(t) for t in text_parts)} символів",
                                  flush=True)
                elif event == "message_start":
                    usage["input"] = data.get("message", {}).get(
                        "usage", {}).get("input_tokens")
                elif event == "message_delta":
                    stop = data.get("delta", {}).get("stop_reason", stop)
                    usage["output"] = data.get("usage", {}).get("output_tokens")
                elif event == "error":
                    return None, 0, str(data)[:300], stop, usage

    return "".join(text_parts).strip(), 200, None, stop, usage


def call_api(key, system, user, max_tokens=None):
    payload = {"model": MODEL, "max_tokens": max_tokens or MAX_TOKENS,
               "system": system, "messages": [{"role": "user", "content": user}]}

    for attempt in range(ATTEMPTS):
        try:
            text, code, err, stop, usage = stream_once(key, payload)
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError,
                httpx.ReadError) as exc:
            print(f"  спроба {attempt + 1}: {type(exc).__name__}")
            if attempt == ATTEMPTS - 1:
                sys.exit(f"API не відповів за {ATTEMPTS} спроби")
            time.sleep(10 * (attempt + 1))
            continue

        if code in (429, 529) or code >= 500:
            print(f"  спроба {attempt + 1}: API перевантажений ({code})")
            if attempt == ATTEMPTS - 1:
                sys.exit(f"API перевантажений ({code})")
            time.sleep(20 * (attempt + 1))
            continue
        if code >= 400:
            sys.exit(f"API повернув {code}: {err}")

        print(f"  вхід {usage['input']} | вихід {usage['output']} | зупинка: {stop}")
        if stop == "max_tokens":
            print("  УВАГА: обірвано лімітом токенів")
        return text

    sys.exit("API не відповів")


def split_parts(text, require="brief"):
    """Ділить відповідь за маркерами. Якщо обов'язкового маркера немає —
    для випуску вважаємо весь текст брифом, для стану нічого не чіпаємо."""
    if not text or MARKERS[require] not in text:
        return ({"brief": text}, False) if require == "brief" else ({}, False)

    # Порядок розбору не залежить від порядку в тексті — беремо за позиціями.
    order = ["greeting", "hook", "brief", "calendar", "threads",
             "predictions", "external"]
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
    text = call_api(key, (ROOT / "prompts" / "weekly.md").read_text(encoding="utf-8"),
                    user, MAX_TOKENS)
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

    # Два окремі запити замість одного. При одному відповідь стабільно
    # не вкладалась у ліміт: міркування з'їдали бюджет, і файли стану,
    # які стоять у кінці, обривались. Тепер у кожного запиту свій бюджет.
    print("Запит 1: випуск...")
    text = call_api(key, (ROOT / "prompts" / "brief.md").read_text(encoding="utf-8"),
                    user, MAX_TOKENS)
    if not text:
        sys.exit("API повернув порожню відповідь")

    parts, structured = split_parts(text)
    brief = parts.get("brief", "").strip()
    if not brief:
        sys.exit("У відповіді немає тексту брифу")
    if not structured:
        print("УВАГА: маркерів немає у відповіді на перший запит")

    print("Запит 2: файли стану...")
    state_user = (f"СЬОГОДНІШНІЙ ВИПУСК:\n{brief}\n\n"
                  f"ПОТОЧНИЙ КАЛЕНДАР:\n{read_state('calendar')}\n\n"
                  f"ПОТОЧНА ПАМ'ЯТЬ:\n{read_state('threads')}\n\n"
                  f"НАШІ ПРОГНОЗИ:\n{read_state('predictions')}\n\n"
                  f"ЧУЖІ ПРОГНОЗИ:\n{read_state('external')}\n\n"
                  f"СЬОГОДНІ {today}")
    state_text = call_api(
        key, (ROOT / "prompts" / "state.md").read_text(encoding="utf-8"),
        state_user, MAX_TOKENS_STATE)

    state_parts, ok = split_parts(state_text, require="threads")
    if ok:
        missing = [k for k in ("calendar", "threads", "predictions", "external")
                   if not state_parts.get(k, "").strip()]
        if missing:
            print(f"УВАГА: у відповіді немає частин: {', '.join(missing)}")
        save_state(state_parts)
    else:
        print("УВАГА: маркерів у відповіді на другий запит немає, стан не чіпаю")

    (ROOT / "issues").mkdir(exist_ok=True)
    greet = parts.get("greeting", "").strip().split("\n")[0][:60]
    if greet:
        (ROOT / "issues" / f"greet-{today}.txt").write_text(greet, encoding="utf-8")
        print(f"Привітання: {greet}")

    hook = parts.get("hook", "").strip()
    if hook:
        (ROOT / "issues" / f"hook-{today}.txt").write_text(hook, encoding="utf-8")
        print(f"Анонс: {len(hook.splitlines())} рядків")

    (ROOT / "issues" / f"{today}.md").write_text(brief + "\n", encoding="utf-8")
    (ROOT / "issues" / "latest.md").write_text(brief + "\n", encoding="utf-8")
    # Мітка свіжості: публікація й відправка орієнтуються на неї, а не на
    # наявність файлу. Інакше повторний запуск того ж дня випустив би
    # попередній випуск ще раз.
    (ROOT / "state" / "last-write.txt").write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8")

    print(f"Бріф: {len(brief)} символів")
    if len(brief) < 3000:
        print("УВАГА: бріф підозріло короткий, очікується 6000-9000")

    # Неділя — додатково тижневий огляд
    if datetime.now(timezone.utc).weekday() == 6:
        weekly(key, today)


if __name__ == "__main__":
    main()

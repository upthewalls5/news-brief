#!/usr/bin/env python3
"""
write.py — перетворює дайджест на готовий бріф через Anthropic API.

Читає:  digests/latest.md, prompts/brief.md
Пише:   issues/YYYY-MM-DD.md, issues/latest.md
Потрібен секрет: ANTHROPIC_API_KEY

Текст промпту лежить окремо в prompts/brief.md — щоб правити формат випуску
не чіпаючи код.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-sonnet-5"
VERSION = "2026-08-28.5"
# Ліміт спільний для міркувань моделі та самого тексту. При 2000 роздуми
# з'їдали майже все, і випуск обривався на середині першого блоку.
MAX_TOKENS = 12000   # довший випуск + міркування моделі
TIMEOUT = 900.0      # 100 КБ на вхід і 1200 слів на вихід не вкладаються в 180 с
ATTEMPTS = 3

# Запобіжник від несподівано величезного дайджесту (наприклад, якщо якась стрічка
# почне віддавати повні тексти). Обрізаємо, а не платимо за сюрприз.
MAX_DIGEST_CHARS = 120_000


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Немає секрету ANTHROPIC_API_KEY")

    print(f"write.py версія {VERSION}")
    digest = (ROOT / "digests" / "latest.md").read_text(encoding="utf-8")
    if len(digest) > MAX_DIGEST_CHARS:
        digest = digest[:MAX_DIGEST_CHARS] + "\n\n[дайджест обрізано за розміром]"
        print(f"УВАГА: дайджест обрізано до {MAX_DIGEST_CHARS} символів")

    prompt = (ROOT / "prompts" / "brief.md").read_text(encoding="utf-8")

    payload = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": prompt,
        "messages": [{"role": "user", "content": digest}],
    }

    r = None
    for attempt in range(ATTEMPTS):
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                r = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
            break
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
            print(f"Спроба {attempt + 1}: {type(exc).__name__}")
            if attempt == ATTEMPTS - 1:
                sys.exit(f"API не відповів за {ATTEMPTS} спроби: {type(exc).__name__}")
            time.sleep(10 * (attempt + 1))

    if r.status_code in (429, 529) or r.status_code >= 500:
        sys.exit(f"API перевантажений ({r.status_code}). Спробуйте перезапустити.")
    if r.status_code >= 400:
        sys.exit(f"API повернув {r.status_code}: {r.text[:400]}")

    data = r.json()
    text = "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()

    if not text:
        sys.exit("API повернув порожню відповідь")

    usage = data.get("usage", {})
    stop = data.get("stop_reason")
    print(f"Вхід: {usage.get('input_tokens')} токенів | "
          f"вихід: {usage.get('output_tokens')} | причина зупинки: {stop} | "
          f"довжина брифу: {len(text)} символів")

    if stop == "max_tokens":
        print("УВАГА: випуск обірвано лімітом токенів. Підніміть MAX_TOKENS.")
    if len(text) < 3000:
        print(f"УВАГА: бріф підозріло короткий ({len(text)} символів). "
              "Очікується 6000-9000.")

    today = datetime.now(timezone.utc).date().isoformat()
    (ROOT / "issues").mkdir(exist_ok=True)
    (ROOT / "issues" / f"{today}.md").write_text(text + "\n", encoding="utf-8")
    (ROOT / "issues" / "latest.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

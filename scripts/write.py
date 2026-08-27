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
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-sonnet-5"
MAX_TOKENS = 2000

# Запобіжник від несподівано величезного дайджесту (наприклад, якщо якась стрічка
# почне віддавати повні тексти). Обрізаємо, а не платимо за сюрприз.
MAX_DIGEST_CHARS = 120_000


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("Немає секрету ANTHROPIC_API_KEY")

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

    with httpx.Client(timeout=180.0) as client:
        r = client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
        )

    if r.status_code >= 400:
        sys.exit(f"API повернув {r.status_code}: {r.text[:400]}")

    data = r.json()
    text = "".join(
        b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
    ).strip()

    if not text:
        sys.exit("API повернув порожню відповідь")

    usage = data.get("usage", {})
    print(f"Вхід: {usage.get('input_tokens')} токенів | "
          f"вихід: {usage.get('output_tokens')} | довжина брифу: {len(text)} символів")

    today = datetime.now(timezone.utc).date().isoformat()
    (ROOT / "issues").mkdir(exist_ok=True)
    (ROOT / "issues" / f"{today}.md").write_text(text + "\n", encoding="utf-8")
    (ROOT / "issues" / "latest.md").write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

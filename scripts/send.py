#!/usr/bin/env python3
"""
send.py — відправляє готовий бріф у Telegram.

Читає:  issues/latest.md
Потрібні секрети: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Надсилає звичайним текстом без розмітки. Це навмисно: Telegram суворий до
markdown і повертає помилку 400 на будь-який неекранований символ. Емодзі,
переноси й відступи в звичайному тексті працюють, а зламатись нема чому.

Повідомлення довші за 4096 символів ріжуться по порожньому рядку.
"""

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 3900  # запас до телеграмівських 4096


def split_message(text: str):
    if len(text) <= LIMIT:
        return [text]
    parts, current = [], ""
    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 > LIMIT:
            if current:
                parts.append(current.strip())
            # окремий блок сам по собі завеликий — ріжемо по рядках
            while len(block) > LIMIT:
                cut = block.rfind("\n", 0, LIMIT)
                cut = cut if cut > 0 else LIMIT
                parts.append(block[:cut].strip())
                block = block[cut:]
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current.strip():
        parts.append(current.strip())
    return parts


def send(token, chat_id, text):
    with httpx.Client(timeout=40.0) as client:
        r = client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Telegram {r.status_code}: {r.text[:300]}")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        sys.exit("Немає секретів TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID")

    path = ROOT / "issues" / "latest.md"
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
    else:
        text = ("Бріф сьогодні не сформувався — дайджест зібрався, "
                "але випуск не написався. Подивіться Actions у репозиторії.")

    parts = split_message(text)
    for i, part in enumerate(parts):
        if len(parts) > 1:
            part = f"{part}\n\n({i + 1}/{len(parts)})"
        send(token, chat_id, part)
        if i < len(parts) - 1:
            time.sleep(1)

    print(f"Відправлено {len(parts)} повідомлень, {len(text)} символів")


if __name__ == "__main__":
    main()

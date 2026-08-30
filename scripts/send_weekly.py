#!/usr/bin/env python3
"""
send_weekly.py — надсилає тижневий огляд окремим повідомленням.

Раніше огляд чіплявся в хвіст недільного випуску: у Telegram виходила
стіна тексту, у Telegraph він переповнював сторінку, а на сайті губився
під випуском. Тепер це окрема доставка о власній годині.

Запускається зовнішнім тригером у неділю об 11:00 за Києвом.
Якщо огляду за сьогодні немає — тихо виходить.

Читає:  issues/weekly-YYYY-MM-DD.md
Секрети: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from send import decorate, esc, send, split_message

ROOT = Path(__file__).resolve().parent.parent
MONTHS = ("січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        sys.exit("Немає TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID")

    today = datetime.now(timezone.utc).date()
    path = ROOT / "issues" / f"weekly-{today.isoformat()}.md"
    if not path.exists():
        print(f"Огляду за {today} немає — сьогодні не неділя або він не склався")
        return

    # Захист від дубля: зовнішній тригер і запасний розклад можуть
    # спрацювати обидва, і огляд прийшов би двічі.
    mark = ROOT / "state" / "weekly-sent.txt"
    if mark.exists() and mark.read_text(encoding="utf-8").strip() == today.isoformat():
        source = os.environ.get("TRIGGER_SOURCE", "manual").strip().lower()
        if source == "cron":
            print("Огляд за сьогодні вже надіслано, пропускаю")
            return
        print("Огляд уже надсилали сьогодні, але запуск ручний — шлю ще раз")

    text = path.read_text(encoding="utf-8").strip()
    if len(text) < 300:
        print(f"Огляд підозріло короткий ({len(text)} символів), не надсилаю")
        return

    header = f"📅 ОГЛЯД ТИЖНЯ · {today.day} {MONTHS[today.month - 1]} {today.year}"
    parts = split_message(text)
    for i, part in enumerate(parts):
        body = decorate(part)
        if i == 0:
            body = f"<b>{esc(header)}</b>\n\n{body}"
        send(token, chat_id, body)
    mark.parent.mkdir(exist_ok=True)
    mark.write_text(today.isoformat(), encoding="utf-8")
    print(f"Огляд тижня надіслано: {len(text)} символів, {len(parts)} повідомлень")


if __name__ == "__main__":
    main()

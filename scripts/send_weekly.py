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


def first_paragraph(text, limit=700):
    """Перший змістовний абзац — «тиждень одним абзацом». Заголовки
    рубрик пропускаємо: вони без тексту нічого не кажуть."""
    for block in text.split("\n\n"):
        b = block.strip()
        if len(b) < 120 or b.isupper():
            continue
        return b if len(b) <= limit else b[:limit].rsplit(" ", 1)[0] + "…"
    return text[:limit]


def publish_weekly(text, today):
    """Окрема сторінка на telegra.ph. Своя адреса, не пов'язана з випуском."""
    try:
        import publish as P
    except Exception as exc:
        print(f"publish.py недоступний ({type(exc).__name__})")
        return ""
    token = os.environ.get("TELEGRAPH_TOKEN", "").strip()
    if not token:
        print("Немає TELEGRAPH_TOKEN, сторінку не створюю")
        return ""

    nodes = P.build_nodes(text)
    slug = P.secrets.token_hex(3)
    title = f"Огляд тижня {today.day} {MONTHS[today.month - 1]} {today.year}"
    try:
        with P.httpx.Client(timeout=60.0) as client:
            r = client.post(f"{P.API}/createPage", json={
                "access_token": token, "title": f"w{slug}",
                "author_name": "Ранковий бріф",
                "content": P.fit_content(nodes, P.LIMIT_SAFE),
                "return_content": False,
            })
            data = r.json()
            if not data.get("ok"):
                print(f"Telegraph відмовив: {str(data)[:160]}")
                return ""
            url = data["result"]["url"]
            path = data["result"].get("path")
            if path:
                client.post(f"{P.API}/editPage/{path}", json={
                    "access_token": token, "title": title[:256],
                    "author_name": "Ранковий бріф",
                    "content": P.fit_content(nodes, P.LIMIT_SAFE),
                    "return_content": False,
                })
            return url
    except Exception as exc:
        print(f"Сторінка не створилась ({type(exc).__name__}: {exc})")
        return ""


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

    # Огляд великий — сім тисяч символів у стрічці читати незручно.
    # Тому повний текст іде на telegra.ph окремою сторінкою зі своєю
    # адресою, а в канал — перший абзац і посилання.
    link = publish_weekly(text, today)

    if link:
        body = (f"<b>{esc(header)}</b>\n\n{decorate(first_paragraph(text))}"
                f"\n\n📄 Огляд повністю: {link}")
        send(token, chat_id, body)
        print(f"Огляд тижня: {len(text)} символів, сторінка {link}")
    else:
        parts = split_message(text)
        for i, part in enumerate(parts):
            body = decorate(part)
            if i == 0:
                body = f"<b>{esc(header)}</b>\n\n{body}"
            send(token, chat_id, body)
        print(f"Сторінки немає, надіслано текстом: {len(parts)} повідомлень")

    mark.parent.mkdir(exist_ok=True)
    mark.write_text(today.isoformat(), encoding="utf-8")


if __name__ == "__main__":
    main()

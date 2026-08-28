#!/usr/bin/env python3
"""
probe_telegram.py — перевіряє, чи вдається читати видання через Telegram.

У публічного каналу є веб-версія t.me/s/<канал> — звичайний HTML,
без ключа й авторизації. Пости там це заголовок, лід і посилання,
тобто рівно те, що потрібно дайджесту.

Читає:  social.csv (кілька кандидатів на видання через |)
Пише:   telegram-coverage.md, telegram-hosts.json

Імена каналів у social.csv — здогади. Саме тому вони перевіряються,
а не вписуються одразу в збір.
"""

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://t.me/s/"
PAUSE = 1.0
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MSG_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TIME_RE = re.compile(r'<time datetime="([^"]+)"')


def strip_tags(html: str) -> str:
    html = re.sub(r"<br\s*/?>", " ", html)
    html = re.sub(r"<[^>]+>", "", html)
    html = (html.replace("&amp;", "&").replace("&quot;", '"')
                .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&nbsp;", " "))
    return re.sub(r"\s+", " ", html).strip()


def parse_channel(html: str):
    """Повертає (кількість постів, найсвіжіша дата, приклад заголовка)."""
    posts = [strip_tags(m) for m in MSG_RE.findall(html)]
    posts = [p for p in posts if len(p) > 25]
    times = TIME_RE.findall(html)
    newest = times[-1] if times else "?"
    return len(posts), newest, (posts[-1][:70] if posts else "")


def fresh_enough(stamp: str, max_hours: int = 48) -> bool:
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except Exception:
        return True          # не змогли розібрати — не відкидаємо
    age = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    return age <= max_hours


def probe(client, channel):
    try:
        r = client.get(BASE + channel)
    except Exception as exc:
        return None, f"{type(exc).__name__}"
    if r.status_code == 404:
        return 0, "каналу немає"
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}"
    if "tgme_widget_message" not in r.text:
        return 0, "не публічний або порожній"
    n, newest, sample = parse_channel(r.text)
    if not n:
        return 0, "постів не видно"
    if not fresh_enough(newest):
        return 0, f"занедбаний, останнє {newest[:10]}"
    return n, f"{n} постів, останній {newest[:16]}, «{sample}»"


def main():
    src = ROOT / "social.csv"
    if not src.exists():
        sys.exit("Немає social.csv")
    rows_in = list(csv.DictReader(src.open(encoding="utf-8")))
    print(f"Перевіряю {len(rows_in)} видань у Telegram\n")

    rows, found = [], {}
    with httpx.Client(timeout=30.0, headers={"User-Agent": UA},
                      follow_redirects=True) as client:
        for row in rows_in:
            name = row["name"]
            hit = None
            note = "жоден кандидат не підійшов"
            for ch in row["channels"].split("|"):
                ch = ch.strip()
                if not ch:
                    continue
                n, msg = probe(client, ch)
                time.sleep(PAUSE)
                if n:
                    hit, note = ch, msg
                    break
                note = f"{ch}: {msg}"
            if hit:
                found[name] = hit
                mark = "Є"
            else:
                mark = "Немає"
            print(f"  {mark:<8} {name:<24} {note}", flush=True)
            rows.append((name, hit or "—", mark, note.replace("|", "/")))

    have = len(found)
    lines = [
        "# Покриття через Telegram",
        "",
        f"Перевірено видань: **{len(rows)}**",
        f"- Знайдено канал: **{have}**",
        f"- Немає: **{len(rows) - have}**",
        "",
        "| Видання | Канал | Статус | Примітка |",
        "|---|---|---|---|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    (ROOT / "telegram-coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "telegram-hosts.json").write_text(
        json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nЗнайдено каналів: {have} з {len(rows)}")


if __name__ == "__main__":
    main()

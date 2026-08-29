#!/usr/bin/env python3
"""
telegram_feed.py — забирає дописи з публічних Telegram-каналів видань,
до яких немає доступу через RSS.

Наразі це Іран та Ізраїль: Fars, Etemad і Calcalist інакше недосяжні.

Важлива відмінність від решти джерел: допис у каналі — це АНОНС, а не
редакційний матеріал. Він коротший, емоційніший і часто про місцеву
поточну повістку. Тому таких джерел мало, беремо з кожного лише кілька
найсвіжіших, і позначаємо окремо, щоб модель розуміла, що читає.

Читає:  social.csv
Повертає список матеріалів у тому ж форматі, що й collect.py.
"""

import re
from datetime import datetime, timezone

import httpx

BASE = "https://t.me/s/"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

MSG = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TIME = re.compile(r'<time datetime="([^"]+)"')

PER_CHANNEL = 6          # анонсів з каналу: більше — це вже стрічка місцевих новин
MIN_LEN = 40             # коротші дописи майже завжди службові


def strip_tags(html):
    html = re.sub(r"<br\s*/?>", " ", html)
    html = re.sub(r"<[^>]+>", " ", html)
    for a, b in (("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
                 ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")):
        html = html.replace(a, b)
    return re.sub(r"\s+", " ", html).strip()


def fetch(client, channel):
    try:
        r = client.get(BASE + channel)
    except Exception as exc:
        return None, type(exc).__name__
    if r.status_code >= 400 or "tgme_widget_message" not in r.text:
        return None, f"HTTP {r.status_code}"
    return r.text, None


def parse(html, cutoff):
    posts = [strip_tags(m) for m in MSG.findall(html)]
    stamps = TIME.findall(html)
    # У розмітці порядок збігається: беремо з кінця, там найсвіжіші
    pairs = list(zip(posts[-40:], stamps[-40:]))[::-1]
    out = []
    for text, stamp in pairs:
        if len(text) < MIN_LEN:
            continue
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if dt < cutoff:
                continue
            when = dt.isoformat()
        except Exception:
            when = ""
        out.append((text, when))
        if len(out) >= PER_CHANNEL:
            break
    return out


def collect(root, cutoff, norm, is_noise):
    """norm та is_noise передає collect.py, щоб чистка була однакова."""
    import csv
    path = root / "social.csv"
    if not path.exists():
        return [], []

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    items, dead = [], []
    with httpx.Client(timeout=25.0, headers={"User-Agent": UA},
                      follow_redirects=True) as client:
        for row in rows:
            html, err = fetch(client, row["channel"])
            if html is None:
                dead.append(f"{row['name']} (Telegram {err})")
                continue
            got = 0
            for text, when in parse(html, cutoff):
                title = norm(text)[:220]
                if not title or is_noise(title, []):
                    continue
                items.append({
                    "title": title,
                    "lead": "",
                    "link": f"https://t.me/{row['channel']}",
                    "when": when,
                    "country": row["country"],
                    "source": f"{row['name']} (Telegram)",
                    "pole": row["pole"],
                })
                got += 1
            if got == 0:
                dead.append(f"{row['name']} (Telegram порожньо)")

    print(f"Telegram: {len(items)} анонсів з {len(rows) - len(dead)} каналів")
    return items, dead

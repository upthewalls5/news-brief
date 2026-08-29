#!/usr/bin/env python3
"""
probe_social.py — шукає офіційні акаунти видань там, де RSS недоступний.

Перевіряє три платформи, які віддають публічні дані без ключів:
  Telegram  — t.me/s/<канал>, звичайний HTML
  Bluesky   — відкритий AT Protocol, публічний ендпоінт
  Mastodon  — відкритий API інстансу

Свідомо НЕ перевіряємо:
  X        — API закритий, безкоштовного доступу немає
  Meta     — потрібен бізнес-акаунт і верифікація застосунку
  WhatsApp — у каналів немає публічного API взагалі
  Weibo/WeChat — потрібен китайський акаунт; Китай окремим скриптом

Читає:  feed-report.md (кого не вдалося взяти через RSS)
        social.csv (кандидати, якщо є)
Пише:   social-coverage.md, social-hosts.json
"""

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
PAUSE = 0.8

TG_MSG = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
TG_TIME = re.compile(r'<time datetime="([^"]+)"')

MASTODON_HOSTS = ("mastodon.social", "mstdn.social", "journa.host",
                  "social.network.europa.eu", "respublicae.eu")


def strip_tags(html):
    html = re.sub(r"<br\s*/?>", " ", html)
    html = re.sub(r"<[^>]+>", "", html)
    for a, b in (("&amp;", "&"), ("&quot;", '"'), ("&#39;", "'"),
                 ("&lt;", "<"), ("&gt;", ">"), ("&nbsp;", " ")):
        html = html.replace(a, b)
    return re.sub(r"\s+", " ", html).strip()


def fresh(stamp, max_days=7):
    try:
        dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except Exception:
        return True
    return (datetime.now(timezone.utc) - dt).days <= max_days


def try_telegram(client, handle):
    try:
        r = client.get(f"https://t.me/s/{handle}")
    except Exception as exc:
        return None, type(exc).__name__
    if r.status_code >= 400 or "tgme_widget_message" not in r.text:
        return None, "немає або закритий"
    posts = [strip_tags(m) for m in TG_MSG.findall(r.text)]
    posts = [p for p in posts if len(p) > 25]
    times = TG_TIME.findall(r.text)
    if not posts:
        return None, "постів не видно"
    if times and not fresh(times[-1]):
        return None, f"занедбаний, останнє {times[-1][:10]}"
    return len(posts), f"{len(posts)} постів, «{posts[-1][:52]}»"


def try_bluesky(client, handle):
    """Публічний ендпоінт AT Protocol — без токена й реєстрації."""
    url = ("https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"
           f"?actor={quote(handle)}&limit=10")
    try:
        r = client.get(url)
    except Exception as exc:
        return None, type(exc).__name__
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}"
    feed = r.json().get("feed") or []
    if not feed:
        return None, "порожньо"
    post = feed[0].get("post", {}).get("record", {})
    when = post.get("createdAt", "")
    if when and not fresh(when):
        return None, f"занедбаний, останнє {when[:10]}"
    return len(feed), f"{len(feed)} постів, «{str(post.get('text',''))[:52]}»"


def try_mastodon(client, handle):
    """handle у вигляді user@instance або просто user — тоді перебираємо
    відомі інстанси, де осідають медіа."""
    if "@" in handle:
        user, host = handle.split("@", 1)
        hosts = [host]
    else:
        user, hosts = handle, list(MASTODON_HOSTS)
    for host in hosts:
        try:
            r = client.get(f"https://{host}/api/v1/accounts/lookup?acct={quote(user)}")
            if r.status_code >= 400:
                continue
            acct_id = r.json().get("id")
            s = client.get(f"https://{host}/api/v1/accounts/{acct_id}/statuses?limit=10")
            posts = s.json() if s.status_code < 400 else []
            if not posts:
                continue
            when = posts[0].get("created_at", "")
            if when and not fresh(when):
                continue
            return len(posts), f"{host}: {len(posts)} постів"
        except Exception:
            continue
    return None, "не знайдено на відомих інстансах"


def candidates():
    """Хто нам потрібен і які варіанти нікнеймів пробувати."""
    rows = []
    social = ROOT / "social.csv"
    if social.exists():
        for r in csv.DictReader(social.open(encoding="utf-8")):
            rows.append((r["name"], [h.strip() for h in r["channels"].split("|")]))
        return rows

    report = ROOT / "feed-report.md"
    if not report.exists():
        sys.exit("Немає ні social.csv, ні feed-report.md")
    for line in report.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "Країна" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = cells[1]
        slug = re.sub(r"[^a-z0-9]", "", name.lower())
        rows.append((name, [slug, slug + "news", slug + "official"]))
    return rows


def main():
    rows = candidates()
    print(f"Перевіряю {len(rows)} видань на трьох платформах\n")

    found, table = {}, []
    with httpx.Client(timeout=25.0, headers={"User-Agent": UA},
                      follow_redirects=True) as client:
        for name, handles in rows:
            hit = None
            for handle in handles:
                if not handle:
                    continue
                for platform, fn in (("telegram", try_telegram),
                                     ("bluesky", try_bluesky),
                                     ("mastodon", try_mastodon)):
                    n, note = fn(client, handle)
                    time.sleep(PAUSE)
                    if n:
                        hit = (platform, handle, note)
                        break
                if hit:
                    break
            if hit:
                platform, handle, note = hit
                found[name] = {"platform": platform, "handle": handle}
                print(f"  {platform:<9} {name:<24} {note}", flush=True)
                table.append((name, platform, handle, note))
            else:
                print(f"  {'—':<9} {name:<24} ніде не знайдено", flush=True)
                table.append((name, "—", "—", "ніде не знайдено"))

    lines = [
        "# Покриття через соцмережі", "",
        f"Перевірено видань: **{len(table)}**",
        f"- Знайдено акаунт: **{len(found)}**",
        f"- Немає: **{len(table) - len(found)}**", "",
        "Перевірялись Telegram, Bluesky і Mastodon — єдині платформи, що "
        "віддають публічні дані без ключів. X, Meta та WhatsApp закриті "
        "технічно, Weibo і WeChat потребують китайського акаунта.", "",
        "| Видання | Платформа | Акаунт | Примітка |", "|---|---|---|---|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in table]
    (ROOT / "social-coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "social-hosts.json").write_text(
        json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nЗнайдено {len(found)} із {len(table)}")


if __name__ == "__main__":
    main()

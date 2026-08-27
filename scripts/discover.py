#!/usr/bin/env python3
"""
discover.py — знаходить і перевіряє RSS-стрічку для кожного видання з sources.csv.

Запускається вручну (workflow "discover"), не щодня. Результат:
  feeds.json       — тільки живі стрічки, з поміткою ваги (легка/важка)
  feed-report.md   — звіт: що працює, що ні, і чому

Логіка пошуку стрічки для домену:
  1. <link rel="alternate" type="application/rss+xml"> у <head>
  2. посилання на сторінці, схожі на стрічку
  3. перебір типових шляхів (/rss, /feed, /rss.xml ...)
Далі кожен кандидат перевіряється по-справжньому: чи парситься, чи є свіжі записи.
"""

import asyncio
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import ssl

import feedparser
import httpx

ROOT = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/html;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
CONCURRENCY = 6
RETRIES = 2          # ConnectError на раннері GitHub — майже завжди тимчасовий
LIMITS = httpx.Limits(max_connections=12, max_keepalive_connections=6)

# Транспорт лишаємо дефолтним: хай сам обирає IPv4 чи IPv6 залежно від того,
# що є в домена.
def make_transport():
    # Без local_address: примусовий IPv4 робив недосяжними домени, у яких
    # є лише AAAA-запис (apnews.com і десятки інших).
    return httpx.AsyncHTTPTransport(retries=1)
TIMEOUT = httpx.Timeout(20.0, connect=10.0)

CANDIDATE_PATHS = [
    "/rss", "/feed", "/rss.xml", "/feed.xml", "/atom.xml", "/index.xml",
    "/rss/all", "/feeds/all.xml", "/rss/index.xml", "/en/rss",
    "/arc/outboundfeeds/rss/", "/rss/news", "/news/rss", "/rssfeeds",
    "/feed/", "/rss/all", "/rss/top", "/en/rss", "/rss/news.xml",
    "/?feed=rss2", "/rss/rss.xml", "/feeds/posts/default",
]

# Стрічка часто живе не на домені видання, а на сусідньому піддомені.
# Саме через це в першій перевірці впала BBC.
SUBDOMAINS = ["feeds.", "rss.", "feed.", "en.", "english."]

# Стрічка вважається "важкою", якщо середній запис довший за це число символів.
# Важкі стрічки віддають повний текст статті замість ліду — їх беремо в обмеженій кількості.
HEAVY_CHARS = 1200


def entry_text(e) -> str:
    parts = [e.get("title", "") or "", e.get("summary", "") or ""]
    for c in e.get("content", []) or []:
        parts.append(c.get("value", "") or "")
    return " ".join(parts)


def assess(raw: bytes, url: str):
    """Парсить стрічку. Повертає (ok, кількість_записів, свіжість_годин, вага, помилка)."""
    parsed = feedparser.parse(raw)
    if parsed.bozo and not parsed.entries:
        return False, 0, None, None, f"не парситься: {type(parsed.bozo_exception).__name__}"
    if not parsed.entries:
        return False, 0, None, None, "стрічка порожня"

    now = datetime.now(timezone.utc)
    newest = None
    for e in parsed.entries:
        st = e.get("published_parsed") or e.get("updated_parsed")
        if st:
            dt = datetime(*st[:6], tzinfo=timezone.utc)
            if newest is None or dt > newest:
                newest = dt
    age_h = round((now - newest).total_seconds() / 3600, 1) if newest else None

    sample = parsed.entries[: min(8, len(parsed.entries))]
    avg = sum(len(entry_text(e)) for e in sample) / len(sample)
    weight = "heavy" if avg > HEAVY_CHARS else "light"

    if age_h is not None and age_h > 168:
        return False, len(parsed.entries), age_h, weight, f"застаріла: найновіше {age_h} год тому"
    return True, len(parsed.entries), age_h, weight, None


TRANSIENT = ("ConnectError", "ConnectTimeout", "ReadTimeout",
             "RemoteProtocolError", "ReadError", "PoolTimeout")


INSECURE = ssl.create_default_context()
INSECURE.check_hostname = False
INSECURE.verify_mode = ssl.CERT_NONE
INSECURE.set_ciphers("DEFAULT@SECLEVEL=1")   # старі сайти з застарілим рукостисканням


async def try_insecure(url):
    """Останній шанс для сайтів зі зламаним TLS. Ми лише читаємо публічний RSS."""
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, verify=INSECURE,
                                     transport=httpx.AsyncHTTPTransport(
                                         verify=INSECURE)) as c:
            r = await c.get(url, follow_redirects=True)
        return (r, None) if r.status_code < 400 else (None, f"HTTP {r.status_code}")
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:100]}"


async def try_url(client, url):
    """Повертає (відповідь, помилка). Мережеві збої повторює з відступом."""
    err = None
    for attempt in range(RETRIES):
        try:
            r = await client.get(url, follow_redirects=True)
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:120]}"
            if "SSL" in err or "CERTIFICATE" in err.upper():
                r2, e2 = await try_insecure(url)
                if r2 is not None:
                    return r2, None
                err = e2 or err
                return None, err
            if err.split(":")[0] in TRANSIENT and attempt < RETRIES - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return None, err
        if r.status_code in (429, 502, 503, 504) and attempt < RETRIES - 1:
            await asyncio.sleep(2.0 * (attempt + 1))
            err = f"HTTP {r.status_code}"
            continue
        if r.status_code >= 400:
            return None, f"HTTP {r.status_code}"
        return r, None
    return None, err


async def find_feed(client, row):
    """Повертає dict з результатом для одного видання."""
    out = {k: row[k] for k in ("country", "name", "lang", "domain", "pole", "tier")}
    domain = row["domain"].strip().rstrip("/")

    # Якщо в CSV уже є готова адреса стрічки — перевіряємо тільки її.
    explicit = (row.get("feed") or "").strip()
    candidates = []
    home_err = None

    # У колонці feed може бути кілька кандидатів через | — перевіряємо всі.
    if explicit:
        candidates += [u.strip() for u in explicit.split("|") if u.strip()]
    base = f"https://{domain}"
    bare = re.sub(r"^www\.", "", domain)
    html = ""

    # Головну смикаємо лише коли явної адреси немає — інакше це зайвий запит.
    if not explicit:
        r, home_err = await try_url(client, base)
        html = r.text if r is not None else ""

    if html:
        for m in re.finditer(
            r'<link[^>]+rel=["\']alternate["\'][^>]*>', html, re.I
        ):
            tag = m.group(0)
            if not re.search(r'type=["\'][^"\']*(rss|atom|xml)', tag, re.I):
                continue
            href = re.search(r'href=["\']([^"\']+)["\']', tag)
            if href:
                candidates.append(urljoin(str(r.url), href.group(1)))

        if not candidates:
            for m in re.finditer(r'href=["\']([^"\']*(?:rss|feed|atom)[^"\']*)["\']', html, re.I):
                u = urljoin(str(r.url), m.group(1))
                if u not in candidates:
                    candidates.append(u)
            candidates = candidates[:4]

    candidates += [base + p for p in CANDIDATE_PATHS]
    fallback = []
    for sub in SUBDOMAINS:
        fallback += [f"https://{sub}{bare}{p}"
                     for p in ("/rss.xml", "/news/rss.xml", "/rss", "/feed")]

    last_err = home_err and f"головна: {home_err}" or "жодна адреса не віддала стрічку"
    seen_c = set()
    ordered = [u for u in candidates if not (u in seen_c or seen_c.add(u))][:16]
    ordered += [u for u in fallback if u not in seen_c][:12]

    # Якщо до хоста не вдалось під'єднатись, решту адрес на ньому пропускаємо:
    # мовчить весь хост, а не конкретний шлях. Саме це раніше давало
    # 28 марних спроб на кожне недоступне видання.
    dead_hosts = set()

    for url in ordered:
        host = urlparse(url).netloc
        if host in dead_hosts:
            continue
        r, err = await try_url(client, url)
        if r is None:
            last_err = err
            if err.split(":")[0] in ("ConnectError", "ConnectTimeout"):
                dead_hosts.add(host)
            continue
        ok, n, age, weight, why = assess(r.content, url)
        if ok:
            out.update(
                status="ok", feed=str(r.url), entries=n,
                newest_hours=age, weight=weight,
            )
            return out
        last_err = why or "невідома помилка"

    out.update(status="failed", error=last_err)
    return out


async def main():
    print("discover.py версія 2026-08-28.1")
    src = ROOT / "sources.csv"
    rows = list(csv.DictReader(src.open(encoding="utf-8")))
    sem = asyncio.Semaphore(CONCURRENCY)
    results = []

    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, limits=LIMITS,
                                 transport=make_transport()) as client:
        async def guarded(row):
            async with sem:
                res = await find_feed(client, row)
                mark = {"ok": "OK  ", "failed": "FAIL", "unreachable": "DEAD"}[res["status"]]
                extra = res.get("weight", res.get("error", ""))
                print(f"{mark} {res['country']:<14} {res['name']:<28} {extra}", flush=True)
                return res

        results = await asyncio.gather(*(guarded(r) for r in rows))

    live = [r for r in results if r["status"] == "ok"]
    dead = [r for r in results if r["status"] != "ok"]

    (ROOT / "feeds.json").write_text(
        json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    light = sum(1 for r in live if r["weight"] == "light")
    heavy = len(live) - light
    lines = [
        f"# Звіт перевірки стрічок",
        f"",
        f"Дата: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
        f"",
        f"- Перевірено видань: **{len(results)}**",
        f"- Живих стрічок: **{len(live)}** (легких {light}, важких {heavy})",
        f"- Не вдалося: **{len(dead)}**",
        f"",
        f"## Не вдалося — потрібна заміна",
        f"",
        f"| Країна | Видання | Причина |",
        f"|---|---|---|",
    ]
    for r in sorted(dead, key=lambda x: (x["country"], x["name"])):
        lines.append(f"| {r['country']} | {r['name']} | {r.get('error','')} |")

    lines += ["", "## Важкі стрічки (віддають повний текст)", ""]
    for r in sorted((r for r in live if r["weight"] == "heavy"), key=lambda x: x["country"]):
        lines.append(f"- {r['country']} · {r['name']}")

    (ROOT / "feed-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{len(live)} живих / {len(dead)} мертвих. feeds.json і feed-report.md записано.")


if __name__ == "__main__":
    asyncio.run(main())

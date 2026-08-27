#!/usr/bin/env python3
"""
collect.py — щоденний збір. Тягне всі живі стрічки, чистить, групує,
порівнює з архівом і пише один компактний дайджест для Claude.

Уся важка робота тут. У Claude їде тільки digests/YYYY-MM-DD.md.

Запуск: python scripts/collect.py
Читає:  feeds.json, state/seen.json, digests/ (архів)
Пише:   digests/YYYY-MM-DD.md, digests/latest.md, state/seen.json
"""

import asyncio
import json
import re
import unicodedata
from collections import defaultdict
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

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
CONCURRENCY = 8
RETRIES = 2          # мережеві збої на раннері GitHub майже завжди тимчасові
LIMITS = httpx.Limits(max_connections=16, max_keepalive_connections=8)

# Транспорт дефолтний: домени бувають як IPv4, так і IPv6-only.
def make_transport():
    # Без local_address: примусовий IPv4 робив недосяжними домени, у яких
    # є лише AAAA-запис (apnews.com і десятки інших).
    return httpx.AsyncHTTPTransport(retries=1)
TIMEOUT = httpx.Timeout(25.0, connect=10.0)

WINDOW_HOURS = 26          # вікно збору
PER_COUNTRY = 6            # скільки заголовків на країну лишаємо в дайджесті
PER_SOURCE = 8             # скільки записів беремо з однієї стрічки
SEEN_DAYS = 7              # глибина пам'яті для індексу новизни
LEAD_CHARS = 180           # обрізаємо лід — у Claude не потрібен повний текст

# Анти-тригери. Матчаться по заголовку в нижньому регістрі, по всіх мовах одразу.
NOISE = [
    # спорт
    "champions league", "premier league", "transfer", "goal", "match",
    "футбол", "матч", "чемпіонат", "чемпионат", "трансфер", "гол ",
    "fifa", "uefa", "nba", "nfl", "olympic", "олимп", "олімп", "tennis",
    "fussball", "fútbol", "calcio", "スポーツ",
    # шоубіз
    "celebrity", "kardashian", "box office", "grammy", "oscar", "netflix series",
    "селебр", "актриса", "певец", "співак", "серіал", "сериал", "шоу ",
    # дріб'язок
    "horoscope", "recipe", "гороскоп", "рецепт", "погода на",
    "weather forecast", "lottery", "лотере",
]

# Категорії, які деякі стрічки самі позначають
NOISE_CATS = {"sport", "sports", "entertainment", "lifestyle", "culture", "showbiz", "спорт"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&[a-z]+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_noise(title: str, cats) -> bool:
    t = title.lower()
    if any(n in t for n in NOISE):
        return True
    for c in cats or []:
        if (c or "").lower() in NOISE_CATS:
            return True
    return False


def signature(title: str):
    """Ключові токени заголовка — власні назви та довгі слова.
    Використовується і для групування, і для порівняння з архівом."""
    toks = re.findall(r"[A-Za-zÀ-ÿА-Яа-яЁёІіЇїЄєҐґ][\w'-]{3,}", title)
    stop = {
        "that", "with", "from", "have", "this", "will", "says", "said", "after",
        "about", "into", "than", "them", "their", "been", "over", "more", "what",
        "року", "року", "після", "проти", "через", "может", "будет", "года",
    }
    out = set()
    for t in toks:
        low = t.lower()
        if low in stop:
            continue
        out.add(low)
    return out


TRANSIENT = ("ConnectError", "ConnectTimeout", "ReadTimeout",
             "RemoteProtocolError", "ReadError", "PoolTimeout")


async def fetch_one(client, feed):
    """Тягне одну стрічку. Мережевий збій повторює — інакше щоранку тихо
    губилися б десятки джерел, і бріф виходив би дірявим без жодного сигналу."""
    url = feed["feed"]
    err = None
    for attempt in range(RETRIES):
        try:
            r = await client.get(url, follow_redirects=True)
        except Exception as exc:
            err = f"{type(exc).__name__}: {str(exc)[:80]}"
            if err.split(":")[0] in TRANSIENT and attempt < RETRIES - 1:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            return feed, None, err
        if r.status_code in (429, 502, 503, 504) and attempt < RETRIES - 1:
            err = f"HTTP {r.status_code}"
            await asyncio.sleep(2.0 * (attempt + 1))
            continue
        if r.status_code >= 400:
            return feed, None, f"HTTP {r.status_code}"
        return feed, r.content, None
    return feed, None, err


async def gather_all(feeds):
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(headers=HEADERS, timeout=TIMEOUT, limits=LIMITS,
                                 transport=make_transport()) as client:
        async def guarded(f):
            async with sem:
                return await fetch_one(client, f)
        return await asyncio.gather(*(guarded(f) for f in feeds))


def parse_items(feed, raw, cutoff):
    parsed = feedparser.parse(raw)
    items = []
    for e in parsed.entries[:40]:
        st = e.get("published_parsed") or e.get("updated_parsed")
        dt = datetime(*st[:6], tzinfo=timezone.utc) if st else None
        if dt and dt < cutoff:
            continue
        title = norm(e.get("title", ""))
        if not title or len(title) < 12:
            continue
        cats = [c.get("term") for c in (e.get("tags") or [])]
        if is_noise(title, cats):
            continue
        lead = norm(e.get("summary", ""))[:LEAD_CHARS]
        items.append({
            "title": title,
            "lead": lead,
            "link": e.get("link", ""),
            "when": dt.isoformat() if dt else "",
            "country": feed["country"],
            "source": feed["name"],
            "pole": feed["pole"],
        })
        if len(items) >= PER_SOURCE:
            break
    return items


def cluster(items, min_sources=3):
    """Групує матеріали за перетином ключових токенів.
    Працює всередині мови; крос-мовне зіставлення лишаємо Claude."""
    clusters = []
    for it in items:
        sig = signature(it["title"])
        if len(sig) < 3:
            continue
        best, best_score = None, 0
        for c in clusters:
            inter = len(sig & c["sig"])
            score = inter / max(3, min(len(sig), len(c["sig"])))
            if inter >= 3 and score > best_score:
                best, best_score = c, score
        if best and best_score >= 0.45:
            best["items"].append(it)
            best["sig"] |= sig
        else:
            clusters.append({"sig": set(sig), "items": [it]})

    out = []
    for c in clusters:
        countries = {i["country"] for i in c["items"]}
        sources = {i["source"] for i in c["items"]}
        if len(sources) >= min_sources:
            out.append({
                "items": c["items"],
                "countries": sorted(countries),
                "n_sources": len(sources),
                "key": " ".join(sorted(list(c["sig"]))[:8]),
                "sig": c["sig"],
            })
    out.sort(key=lambda c: (len(c["countries"]), c["n_sources"]), reverse=True)
    return out


def load_seen():
    p = ROOT / "state" / "seen.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    limit = (datetime.now(timezone.utc) - timedelta(days=SEEN_DAYS)).date().isoformat()
    return {d: v for d, v in data.items() if d >= limit}


def main():
    print("collect.py версія 2026-08-28.1")
    feeds = json.loads((ROOT / "feeds.json").read_text(encoding="utf-8"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=WINDOW_HOURS)

    results = asyncio.run(gather_all(feeds))

    items, dead = [], []
    per_feed = {}
    for feed, raw, err in results:
        if raw is None:
            dead.append(f"{feed['name']} ({err})")
            continue
        got = parse_items(feed, raw, cutoff)
        per_feed[feed["name"]] = len(got)
        items.extend(got)

    # прибираємо точні дублі заголовків усередині країни
    seen_titles = set()
    uniq = []
    for it in items:
        k = (it["country"], it["title"].lower()[:90])
        if k in seen_titles:
            continue
        seen_titles.add(k)
        uniq.append(it)
    items = uniq

    clusters = cluster(items)

    # індекс новизни: чи бачили цей сюжет за останні 7 днів
    seen = load_seen()
    old_sigs = []
    for day_sigs in seen.values():
        old_sigs.extend(set(s) for s in day_sigs)

    def is_new(c):
        for old in old_sigs:
            if len(c["sig"] & old) >= 4:
                return False
        return True

    today = datetime.now(timezone.utc).date().isoformat()
    seen[today] = [sorted(list(c["sig"]))[:12] for c in clusters[:60]]
    (ROOT / "state").mkdir(exist_ok=True)
    (ROOT / "state" / "seen.json").write_text(
        json.dumps(seen, ensure_ascii=False), encoding="utf-8"
    )

    by_country = defaultdict(list)
    for it in items:
        by_country[it["country"]].append(it)

    L = []
    L.append(f"# Дайджест {today}")
    L.append("")
    L.append(f"Зібрано {len(items)} матеріалів з {len(feeds) - len(dead)} стрічок "
             f"за {WINDOW_HOURS} год.")
    if dead:
        share = len(dead) / max(1, len(feeds))
        if share > 0.25:
            L.append(f"УВАГА: не відповіла {round(share * 100)}% стрічок. "
                     f"Покриття сьогодні неповне — врахуй це у випуску.")
        L.append(f"Не відповіли ({len(dead)}): " + ", ".join(dead[:15])
                 + (" …" if len(dead) > 15 else ""))
    L.append("")

    L.append("## Кластери — сюжети в кількох країнах")
    L.append("")
    L.append("Формат: [джерел / країн] · НОВЕ якщо не траплялось 7 днів")
    L.append("")
    for c in clusters[:18]:
        flag = " · НОВЕ" if is_new(c) else ""
        L.append(f"### [{c['n_sources']} дж. / {len(c['countries'])} країн]{flag} "
                 f"{c['items'][0]['title']}")
        for it in c["items"][:6]:
            L.append(f"- {it['country']} · {it['source']} ({it['pole']}): {it['title']}")
            if it["lead"]:
                L.append(f"  {it['lead']}")
        L.append("")

    L.append("## По країнах")
    L.append("")
    for country in sorted(by_country):
        rows = by_country[country][:PER_COUNTRY]
        L.append(f"### {country}")
        for it in rows:
            L.append(f"- [{it['source']} · {it['pole']}] {it['title']}")
        L.append("")

    L.append("## Посилання на топ-сюжети")
    L.append("")
    for c in clusters[:8]:
        it = c["items"][0]
        if it["link"]:
            L.append(f"- {it['title']} — {it['link']}")

    text = "\n".join(L) + "\n"
    (ROOT / "digests").mkdir(exist_ok=True)
    (ROOT / "digests" / f"{today}.md").write_text(text, encoding="utf-8")
    (ROOT / "digests" / "latest.md").write_text(text, encoding="utf-8")

    print(f"Матеріалів: {len(items)} | кластерів: {len(clusters)} | "
          f"мертвих стрічок: {len(dead)} | розмір дайджесту: {len(text)} символів")


if __name__ == "__main__":
    main()

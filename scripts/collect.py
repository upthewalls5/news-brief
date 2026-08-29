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
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

import feedparser
import httpx

import semantics

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
    return httpx.AsyncHTTPTransport(retries=1, http2=True)
TIMEOUT = httpx.Timeout(25.0, connect=10.0)

WINDOW_HOURS = 26          # вікно збору
MAX_DIGEST = 118_000    # запас під ліміт у write.py
PER_COUNTRY = 14           # заголовків на країну — модель зшиває мови сама
PER_SOURCE = 12            # записів з однієї стрічки
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


# ── Обхід антибот-захисту ──────────────────────────────────────────────
# Cloudflare розрізняє клієнтів за відбитком TLS-рукостискання, а не за
# заголовками. httpx завжди виглядає як робот, скільки User-Agent не став.
# curl_cffi повторює рукостискання справжнього Chrome, і це знімає 403.
# Імпорт захищений: якщо бібліотеки немає, працюємо як раніше.
try:
    from curl_cffi import requests as _cffi
    HAVE_CFFI = True
except Exception:
    HAVE_CFFI = False

BLOCKED_CODES = (401, 403, 405, 406, 429, 503)


def _cffi_get(url):
    r = _cffi.get(url, impersonate="chrome", timeout=30,
                  allow_redirects=True)
    return r.status_code, r.content


async def try_browser(url):
    """Другий захід під виглядом Chrome. Повертає (content, помилка)."""
    if not HAVE_CFFI:
        return None, "curl_cffi недоступний"
    try:
        code, content = await asyncio.to_thread(_cffi_get, url)
    except Exception as exc:
        return None, f"chrome: {type(exc).__name__}"
    if code >= 400:
        return None, f"chrome: HTTP {code}"
    return content, None


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
        if r.status_code in BLOCKED_CODES:
            content, cerr = await try_browser(url)
            if content is not None:
                return feed, content, None
            return feed, None, f"HTTP {r.status_code} ({cerr})"
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


# ── Добір через freenewsapi.ai ─────────────────────────────────────────
# Частина видань закрита для дата-центрів (403) або не має робочої стрічки.
# Для них беремо матеріали з freenewsapi.ai: ключа не треба, квоти немає.
# RSS лишається основним джерелом — API лише закриває дірки.
API_BASE = "https://freenewsapi.ai/v1/search"
API_SIZE = 15


def outlet_owners():
    """Власник видання. Заповнено лише для безсумнівних випадків —
    решта порожні, бо активи перепродують і застарілі дані гірші за їх
    відсутність."""
    owners = {}
    src = ROOT / "sources.csv"
    if src.exists():
        for row in csv.DictReader(src.open(encoding="utf-8")):
            if row.get("owner"):
                owners[row["name"]] = row["owner"]
    return owners


def coverage_check(by_country):
    """Сигнал про втрату покриття: якщо країна ядра дала аномально мало,
    це радше відвалились її стрічки, ніж у країні стало тихо. Без цього
    бріф просто перестав би про неї писати, і ніхто б не помітив."""
    CORE = ["Ukraine", "Russia", "USA", "China", "Germany", "France", "UK",
            "Poland", "EU-Brussels", "Israel", "Iran", "India", "Taiwan",
            "Japan", "South Korea"]
    p = ROOT / "state" / "coverage.json"
    hist = {}
    if p.exists():
        try:
            hist = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            hist = {}

    today = datetime.now(timezone.utc).date().isoformat()
    hist[today] = {c: len(v) for c, v in by_country.items()}
    keep = sorted(hist)[-14:]
    hist = {d: hist[d] for d in keep}
    (ROOT / "state").mkdir(exist_ok=True)
    p.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")

    warnings = []
    past = [d for d in keep if d != today][-7:]
    for c in CORE:
        vals = sorted(hist[d].get(c, 0) for d in past)
        if len(vals) < 3:
            continue
        median = vals[len(vals) // 2]
        now = hist[today].get(c, 0)
        if median >= 8 and now < median * 0.4:
            warnings.append(f"{c}: {now} матеріалів проти звичних ~{median}")
    return warnings


def outlet_meta():
    """Країна й полюс для кожного видання — беремо з реєстру."""
    meta = {}
    src = ROOT / "sources.csv"
    if src.exists():
        for row in csv.DictReader(src.open(encoding="utf-8")):
            meta[row["name"]] = (row["country"], row["pole"])
    return meta


async def fetch_api_outlets(cutoff):
    """Повертає (матеріали, назви_що_не_відповіли)."""
    path = ROOT / "api-hosts.json"
    if not path.exists():
        return [], []
    try:
        hosts = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return [], []
    if not hosts:
        return [], []

    meta = outlet_meta()
    items, dead = [], []

    async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS,
                                 follow_redirects=True) as client:
        for name, host in hosts.items():
            country, pole = meta.get(name, ("Global", "unknown"))
            try:
                r = await client.get(API_BASE, params={
                    "host": host, "date": "24h", "size": API_SIZE, "sort": "date"})
                if r.status_code >= 400:
                    dead.append(f"{name} (API HTTP {r.status_code})")
                    continue
                results = r.json().get("results") or []
            except Exception as exc:
                dead.append(f"{name} (API {type(exc).__name__})")
                continue

            got = 0
            for a in results:
                title = norm(a.get("title", ""))
                if not title or len(title) < 12 or is_noise(title, []):
                    continue
                when = a.get("published_at", "")
                if when:
                    try:
                        dt = datetime.fromisoformat(when.replace("Z", "+00:00"))
                        if dt < cutoff:
                            continue
                    except Exception:
                        pass
                items.append({
                    "title": title,
                    "lead": norm(a.get("description", ""))[:LEAD_CHARS],
                    "link": a.get("url", ""),
                    "when": when,
                    "country": country,
                    "source": name,
                    "pole": pole,
                })
                got += 1
                if got >= PER_SOURCE:
                    break
            if got == 0:
                dead.append(f"{name} (API порожньо)")

    ok_outlets = len({i["source"] for i in items})
    print(f"API добрав {len(items)} матеріалів з {ok_outlets} видань "
          f"(усього в списку {len(hosts)})")
    return items, dead


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


def cluster(items, min_sources=2):
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
            if inter >= 2 and score > best_score:
                best, best_score = c, score
        if best and best_score >= 0.38:
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
    print("collect.py версія 2026-08-29.6")
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

    api_items, api_dead = asyncio.run(fetch_api_outlets(cutoff))
    items.extend(api_items)
    dead.extend(api_dead)


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

    # Таблоїди не беруть участі в кластеризації й не потрапляють у розділ
    # по країнах: інакше вони підмішуються в загальний потік як звичайні
    # джерела, а модель бере з них факти.
    quality = [i for i in items if i["pole"] != "tabloid"]

    model = semantics.load_model()
    if model is not None:
        clusters = semantics.cluster_by_meaning(quality, model)
        print(f"Кластеризація за сенсом: {len(clusters)} кластерів")
    else:
        clusters = cluster(quality)
        print(f"Кластеризація за словами: {len(clusters)} кластерів")
        for c in clusters:
            c.setdefault("vecs", None)

    owners = outlet_owners()
    for c in clusters:
        c["divergence"], c["div_detail"] = semantics.divergence(c)
        c["consensus"] = semantics.fake_consensus(c, owners)
    clusters.sort(key=lambda c: (len(c["countries"]) * 2 + c["n_sources"]
                                 + c["divergence"] / 25), reverse=True)

    # індекс новизни: чи бачили цей сюжет за останні 7 днів
    seen = load_seen()
    old_sigs = []
    for day_sigs in seen.values():
        old_sigs.extend(set(s) for s in day_sigs)

    def sig_of(c):
        s = c.get("sig")
        if s is None:
            s = set()
            for it in c["items"][:4]:
                s |= signature(it["title"])
            c["sig"] = s
        return s

    def is_new(c):
        for old in old_sigs:
            if len(sig_of(c) & old) >= 4:
                return False
        return True

    today = datetime.now(timezone.utc).date().isoformat()
    seen[today] = [sorted(list(sig_of(c)))[:12] for c in clusters[:60]]
    (ROOT / "state").mkdir(exist_ok=True)
    (ROOT / "state" / "seen.json").write_text(
        json.dumps(seen, ensure_ascii=False), encoding="utf-8"
    )

    by_country = defaultdict(list)
    for it in quality:
        by_country[it["country"]].append(it)

    L = []
    L.append(f"# Дайджест {today}")
    L.append("")
    L.append(f"Зібрано {len(items)} матеріалів за {WINDOW_HOURS} год "
             f"({len(feeds)} стрічок RSS + {len(api_items)} через API).")
    if dead:
        share = len(dead) / max(1, len(feeds))
        if share > 0.25:
            L.append(f"УВАГА: не відповіла {round(share * 100)}% стрічок. "
                     f"Покриття сьогодні неповне — врахуй це у випуску.")
        L.append(f"Не відповіли ({len(dead)}): " + ", ".join(dead[:15])
                 + (" …" if len(dead) > 15 else ""))
    L.append("")

    tabs = [i for i in items if i["pole"] == "tabloid"]
    if tabs:
        L.append("## Таблоїди — ТІЛЬКИ як індикатор настроїв")
        L.append("")
        L.append("Ці джерела публікують неперевірене. НЕ бери з них факти, "
                 "цифри й цитати. Використовуй лише в рубриці МАСОВА ОПТИКА "
                 "і лише щоб показати, що саме розганяє масова преса.")
        L.append("")
        for it in tabs[:40]:
            L.append(f"- {it['country']} · {it['source']}: {it['title']}")
        L.append("")

    L.append("## Кластери — сюжети в кількох країнах")
    L.append("")
    L.append("Формат: [джерел / країн] · Р=NN індекс розходження (0-100) ·")
    L.append("НОВЕ якщо не траплялось 7 днів · ПОВТОР якщо вже був у випуску")
    L.append("")
    L.append("Індекс розходження показує, наскільки по-різному подають ту саму")
    L.append("подію. Для РОЗКОЛУ ОПТИКИ бери кластери з найвищим Р, а не")
    L.append("найгучніші. Позначку ПОВТОР не став у ГОЛОВНЕ, якщо в сюжеті")
    L.append("нічого не змінилось: краще взяти свіжіший.")
    L.append("")
    for c in clusters[:25]:
        flag = " · НОВЕ" if is_new(c) else " · ПОВТОР"
        L.append(f"### [{c['n_sources']} дж. / {len(c['countries'])} країн] "
                 f"Р={c['divergence']}{flag} {c['items'][0]['title']}")
        if c.get("consensus"):
            L.append(f"  УВАГА, УЯВНИЙ КОНСЕНСУС: {c['consensus']}. "
                     f"Це одна редакційна лінія, а не кілька підтверджень.")
        if c["div_detail"].get("state_vs_free"):
            L.append("  У кластері є і державні, і незалежні джерела.")
        for it in c["items"][:8]:
            L.append(f"- {it['country']} · {it['source']} ({it['pole']}): {it['title']}")
            if it["lead"]:
                L.append(f"  {it['lead']}")
        L.append("")

    # Слід для самолікування: хто саме не відповів сьогодні.
    # heal_feeds.py рахує поспіль і сам перевідкриває стрічку.
    (ROOT / "state").mkdir(exist_ok=True)
    (ROOT / "state" / "last-dead.json").write_text(
        json.dumps({"date": today,
                    "dead": [d.split(" (")[0] for d in dead],
                    "alive": sorted({i["source"] for i in items})},
                   ensure_ascii=False), encoding="utf-8")

    warns = coverage_check(by_country)
    if warns:
        L.append("## УВАГА: можлива втрата покриття")
        L.append("")
        L.append("Ці країни дали значно менше матеріалів, ніж зазвичай. "
                 "Найімовірніше відвалились їхні стрічки, а не настала тиша. "
                 "Не роби висновку, що в країні спокійно.")
        for w in warns:
            L.append(f"- {w}")
        L.append("")

    country_start = len(L)
    L.append("## По країнах")
    L.append("")
    L.append("Кластери вище зібрані машинно за збігом слів, тому працюють лише "
             "всередині однієї мови. Нижче — сирі заголовки. Крос-мовне "
             "зіставлення роби сам: та сама подія тут присутня різними мовами "
             "й машиною не помічена.")
    L.append("")
    total = max(1, len(quality))
    for country in sorted(by_country):
        rows = by_country[country][:PER_COUNTRY]
        share = round(100 * len(by_country[country]) / total, 1)
        L.append(f"### {country}  ({len(by_country[country])} матеріалів, {share}% дня)")
        for it in rows:
            L.append(f"- [{it['source']} · {it['pole']}] {it['title']}")
        L.append("")

    def rebuild(per):
        """Перескладає розділ по країнах із меншою кількістю заголовків."""
        head = L[:country_start]
        tail = []
        tail.append("## По країнах")
        tail.append("")
        tail.append("Кластери вище зібрані машинно, тому працюють лише "
                    "всередині однієї мови. Нижче — сирі заголовки. "
                    "Крос-мовне зіставлення роби сам.")
        tail.append("")
        for c in sorted(by_country):
            rows = by_country[c][:per]
            share = round(100 * len(by_country[c]) / total, 1)
            tail.append(f"### {c}  ({len(by_country[c])} матеріалів, {share}% дня)")
            for it in rows:
                tail.append(f"- [{it['source']} · {it['pole']}] {it['title']}")
            tail.append("")
        tail.append("## Посилання на топ-сюжети")
        tail.append("")
        for c in clusters[:8]:
            it = c["items"][0]
            if it["link"]:
                tail.append(f"- {it['title']} — {it['link']}")
        return head + tail

    L.append("## Посилання на топ-сюжети")
    L.append("")
    for c in clusters[:8]:
        it = c["items"][0]
        if it["link"]:
            L.append(f"- {it['title']} — {it['link']}")

    text = "\n".join(L) + "\n"

    # Якщо дайджест не вкладається в бюджет, скорочуємо РІВНОМІРНО — по
    # кілька заголовків з кожної країни. Обрив із кінця з'їдав розділ по
    # країнах за абеткою: Україна, США й Тайвань зникали, і модель навіть
    # не знала, що їх не бачила.
    if len(text) > MAX_DIGEST:
        for per in (10, 8, 6, 4, 3):
            L2 = rebuild(per)
            text = "\n".join(L2) + "\n"
            print(f"Дайджест завеликий, скорочую до {per} заголовків на країну "
                  f"→ {len(text)} символів")
            if len(text) <= MAX_DIGEST:
                break
    (ROOT / "digests").mkdir(exist_ok=True)
    (ROOT / "digests" / f"{today}.md").write_text(text, encoding="utf-8")
    (ROOT / "digests" / "latest.md").write_text(text, encoding="utf-8")

    print(f"Матеріалів: {len(items)} | кластерів: {len(clusters)} | "
          f"мертвих стрічок: {len(dead)} | розмір дайджесту: {len(text)} символів")


if __name__ == "__main__":
    main()

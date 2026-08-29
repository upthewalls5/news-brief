#!/usr/bin/env python3
"""
probe_china.py — розвідка трьох шляхів до китайських медіа.

Прямий доступ закритий: Weibo й WeChat вимагають китайського акаунта,
більшість сайтів не має RSS, а англомовні редакції показують експортну
рамку — те, що Китай говорить світу, а не собі.

Перевіряємо три обхідні шляхи:

  1. RSSHub — відкриті маршрути до The Paper, Guancha, Caixin, Yicai,
     гарячого пошуку Weibo. Публічні інстанси обмежують частоту, тож
     перевіряємо кілька дзеркал.
  2. GDELT — індексує китайськомовні видання й віддає заголовки
     безкоштовно. Найнадійніший шлях до внутрішньої рамки.
  3. Спостерігачі — англомовні видання, які професійно читають китайські
     платформи: What's on Weibo стежить за гарячим пошуком, China Digital
     Times за цензурою. Це не заміна першоджерелам, але єдиний спосіб
     побачити внутрішню дискусію без китайського акаунта.

Пише: china-coverage.md
"""

import time
from pathlib import Path

import feedparser
import httpx

ROOT = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
PAUSE = 1.2

RSSHUB_MIRRORS = ["https://rsshub.app", "https://rsshub.rssforever.com",
                  "https://hub.slarker.me"]

RSSHUB_ROUTES = {
    "The Paper (澎湃)": "/thepaper/featured",
    "Guancha (观察者网)": "/guancha/headline",
    "Caixin": "/caixin/latest",
    "Yicai": "/yicai/brief",
    "Weibo гарячий пошук": "/weibo/search/hot",
    "Zhihu гаряче": "/zhihu/hotlist",
    "Baidu гарячі теми": "/baidu/topic",
}

GDELT_DOMAINS = {
    "The Paper": "thepaper.cn",
    "Guancha": "guancha.cn",
    "Caixin (кит.)": "caixin.com",
    "Yicai": "yicai.com",
    "Xinhua (кит.)": "xinhuanet.com",
    "People's Daily (кит.)": "people.com.cn",
    "Global Times (кит.)": "huanqiu.com",
    "Southern Weekly": "infzm.com",
}

OBSERVERS = {
    "What's on Weibo": ["https://www.whatsonweibo.com/feed/"],
    "China Digital Times": ["https://chinadigitaltimes.net/feed/"],
    "Pekingnology": ["https://www.pekingnology.com/feed"],
    "Ginger River Review": ["https://www.gingerriver.com/feed"],
    "ChinaTalk": ["https://www.chinatalk.media/feed"],
    "Sinocism": ["https://sinocism.com/feed"],
    "MERICS": ["https://merics.org/en/rss.xml"],
    "Trivium China": ["https://triviumchina.com/feed/"],
}

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"


def check_feed(client, url):
    try:
        r = client.get(url)
    except Exception as exc:
        return None, type(exc).__name__
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}"
    parsed = feedparser.parse(r.content)
    if not parsed.entries:
        return None, "порожньо або не парситься"
    return len(parsed.entries), parsed.entries[0].get("title", "")[:58]


def check_gdelt(client, host):
    try:
        r = client.get(GDELT, params={"query": f"domainis:{host}", "mode": "artlist",
                                      "format": "json", "timespan": "3d",
                                      "maxrecords": 10, "sort": "datedesc"})
    except Exception as exc:
        return None, type(exc).__name__
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}"
    body = r.text.strip()
    if not body or body.startswith("<"):
        return 0, "порожня відповідь"
    try:
        arts = r.json().get("articles") or []
    except Exception:
        return None, "не JSON"
    if not arts:
        return 0, "нічого за 3 дні"
    a = arts[0]
    return len(arts), f"{a.get('language','?')}, {a.get('title','')[:44]}"


def main():
    sections = []
    with httpx.Client(timeout=35.0, headers={"User-Agent": UA},
                      follow_redirects=True) as client:

        print("1. RSSHub — маршрути до китайських майданчиків\n")
        rows = []
        for name, route in RSSHUB_ROUTES.items():
            hit = None
            for mirror in RSSHUB_MIRRORS:
                n, note = check_feed(client, mirror + route)
                time.sleep(PAUSE)
                if n:
                    hit = (mirror, n, note)
                    break
            if hit:
                mirror, n, note = hit
                print(f"  OK    {name:<24} {mirror} · {note}", flush=True)
                rows.append((name, "OK", mirror + route, note))
            else:
                print(f"  ні    {name:<24} жодне дзеркало не віддало", flush=True)
                rows.append((name, "—", "", "жодне дзеркало не віддало"))
        sections.append(("RSSHub", rows))

        print("\n2. GDELT — китайськомовні видання\n")
        rows = []
        for name, host in GDELT_DOMAINS.items():
            n, note = check_gdelt(client, host)
            time.sleep(PAUSE)
            mark = "OK" if n else "—"
            print(f"  {mark:<5} {name:<24} {note}", flush=True)
            rows.append((name, mark, host, note))
        sections.append(("GDELT", rows))

        print("\n3. Спостерігачі — хто читає китайські платформи за нас\n")
        rows = []
        for name, urls in OBSERVERS.items():
            hit = None
            for u in urls:
                n, note = check_feed(client, u)
                time.sleep(PAUSE)
                if n:
                    hit = (u, note)
                    break
            mark = "OK" if hit else "—"
            print(f"  {mark:<5} {name:<24} {hit[1] if hit else 'недоступно'}",
                  flush=True)
            rows.append((name, mark, hit[0] if hit else "", hit[1] if hit else "недоступно"))
        sections.append(("Спостерігачі", rows))

    lines = ["# Розвідка доступу до китайських медіа", ""]
    for title, rows in sections:
        ok = sum(1 for r in rows if r[1] == "OK")
        lines += [f"## {title} — {ok} з {len(rows)}", "",
                  "| Джерело | Статус | Адреса | Примітка |", "|---|---|---|---|"]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        lines.append("")
    (ROOT / "china-coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nЗаписано china-coverage.md")


if __name__ == "__main__":
    main()

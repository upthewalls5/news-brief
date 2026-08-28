#!/usr/bin/env python3
"""
probe_api.py — перевіряє, які з проблемних видань є у freenewsapi.ai.

Ключа не потрібно: API працює без реєстрації та без квоти.
Перевіряємо кожен домен у двох варіантах — з www і без, бо фільтр host
вимагає точного імені хоста так, як воно стоїть в адресі статті.

Читає:  feed-report.md
Пише:   api-coverage.md, api-hosts.json (готовий до інтеграції список)
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://freenewsapi.ai/v1/search"
PAUSE = 0.6
UA = "news-brief/1.0 (RSS gap filler)"


def failing_outlets():
    report = ROOT / "feed-report.md"
    if not report.exists():
        sys.exit("Немає feed-report.md — спершу запустіть «Перевірити стрічки»")
    out = []
    for line in report.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "Країна" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3:
            continue
        m = re.search(r"\[(https?://[^\]]+)\]", cells[2])
        if not m:
            continue
        host = re.sub(r"^https?://", "", m.group(1)).split("/")[0].lower()
        bare = re.sub(r"^www\.", "", host)
        out.append((cells[0], cells[1], bare))
    return out


def query(client, host):
    try:
        r = client.get(BASE, params={"host": host, "date": "7d", "size": 5,
                                     "sort": "date"})
    except Exception as exc:
        return None, f"{type(exc).__name__}"
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}"
    data = r.json()
    res = data.get("results") or []
    if not res:
        return 0, ""
    return len(res), res[0].get("published_at", "?")


def main():
    outlets = failing_outlets()
    print(f"Перевіряю {len(outlets)} проблемних видань у freenewsapi.ai\n")

    rows, hosts_ok = [], {}
    with httpx.Client(timeout=30.0, headers={"User-Agent": UA},
                      follow_redirects=True) as client:
        for country, name, bare in outlets:
            best = None
            for host in (bare, f"www.{bare}"):
                n, note = query(client, host)
                time.sleep(PAUSE)
                if n:
                    best = (host, n, note)
                    break
                if n is None:
                    best = best or (host, None, note)
            if best and best[1]:
                host, n, newest = best
                hosts_ok[name] = host
                mark, note = f"Є ({n})", f"найсвіжіше {newest}"
            elif best and best[1] is None:
                mark, note = "Помилка", best[2]
            else:
                mark, note = "Немає", "жодної статті за 7 днів"
            print(f"  {mark:<10} {country:<14} {name:<26} {note}", flush=True)
            rows.append((country, name, bare, mark, note))

    have = sum(1 for r in rows if r[3].startswith("Є"))
    lines = [
        "# Покриття freenewsapi.ai",
        "",
        f"Перевірено видань: **{len(rows)}**",
        f"- Є в базі: **{have}**",
        f"- Немає: **{len(rows) - have}**",
        "",
        "| Країна | Видання | Хост | В API | Примітка |",
        "|---|---|---|---|---|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    (ROOT / "api-coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "api-hosts.json").write_text(
        json.dumps(hosts_ok, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nЄ в базі: {have} з {len(rows)}")
    print("Записано: api-coverage.md і api-hosts.json")


if __name__ == "__main__":
    main()

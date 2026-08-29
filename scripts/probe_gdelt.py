#!/usr/bin/env python3
"""
probe_gdelt.py — перевіряє в GDELT ті видання, яких не виявилось у freenewsapi.

GDELT індексує світові медіа, включно з неанглійським сегментом — саме тим,
якого бракує freenewsapi. Ключа не потрібно.

Читає:  api-coverage.md (рядки з поміткою «Немає» або «Помилка»)
Пише:   gdelt-coverage.md, gdelt-hosts.json

Запуск: python scripts/probe_gdelt.py
"""

import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
PAUSE = 2.0          # GDELT публічний і безкоштовний — не женемо
UA = "news-brief/1.0 (RSS gap filler)"


def uncovered():
    """Видання, які freenewsapi не має. Беремо з його ж звіту."""
    path = ROOT / "api-coverage.md"
    if not path.exists():
        sys.exit("Немає api-coverage.md — спершу «Перевірити покриття API»")
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "---" in line or "Країна" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        country, name, host, verdict = cells[0], cells[1], cells[2], cells[3]
        if verdict.startswith("Є"):
            continue
        out.append((country, name, host))
    return out


def query(client, host):
    """domainis — точний збіг домену, інакше 'un.org' зловить 'catholicsun.org'."""
    params = {
        "query": f"domainis:{host}",
        "mode": "artlist",
        "format": "json",
        "timespan": "3d",
        "maxrecords": 10,
        "sort": "datedesc",
    }
    try:
        r = client.get(BASE, params=params)
    except Exception as exc:
        return None, f"{type(exc).__name__}"
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code}"
    body = r.text.strip()
    if not body or body.startswith("<"):
        return 0, "порожня відповідь"
    try:
        arts = r.json().get("articles") or []
    except Exception:
        return None, "відповідь не JSON"
    if not arts:
        return 0, "жодної статті за 3 дні"
    a = arts[0]
    return len(arts), f"{a.get('language','?')}, найсвіжіше {a.get('seendate','?')}"


def main():
    outlets = uncovered()
    print(f"Перевіряю {len(outlets)} видань у GDELT\n")

    rows, hosts_ok = [], {}
    with httpx.Client(timeout=45.0, headers={"User-Agent": UA},
                      follow_redirects=True) as client:
        for country, name, host in outlets:
            n, note = query(client, host)
            if n:
                hosts_ok[name] = host
                mark = f"Є ({n})"
            elif n == 0:
                mark = "Немає"
            else:
                mark = "Помилка"
            print(f"  {mark:<10} {country:<14} {name:<26} {note}", flush=True)
            rows.append((country, name, host, mark, note))
            time.sleep(PAUSE)

    have = sum(1 for r in rows if r[3].startswith("Є"))
    lines = [
        "# Покриття GDELT",
        "",
        f"Перевірено видань: **{len(rows)}**",
        f"- Є в базі: **{have}**",
        f"- Немає: **{len(rows) - have}**",
        "",
        "| Країна | Видання | Хост | В GDELT | Примітка |",
        "|---|---|---|---|---|",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    (ROOT / "gdelt-coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "gdelt-hosts.json").write_text(
        json.dumps(hosts_ok, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nЄ в GDELT: {have} з {len(rows)}")
    print("Записано: gdelt-coverage.md і gdelt-hosts.json")


# ── Агентства ──────────────────────────────────────────────────────────
# Reuters, AP, AFP і Bloomberg не мають публічних RSS. GDELT їх індексує,
# тож заголовки можна брати звідти. Поки лише перевірка: чи справді
# віддає і наскільки свіже.
WIRES = {
    "Reuters": "reuters.com",
    "Associated Press": "apnews.com",
    "AFP": "afp.com",
    "Bloomberg": "bloomberg.com",
}


def probe_wires():
    print("\nПеревірка інформагентств у GDELT")
    with httpx.Client(timeout=45.0, headers={"User-Agent": UA},
                      follow_redirects=True) as client:
        rows = []
        for name, host in WIRES.items():
            n, note = query(client, host)
            mark = f"Є ({n})" if n else ("Немає" if n == 0 else "Помилка")
            print(f"  {mark:<10} {name:<20} {note}", flush=True)
            rows.append((name, host, mark, note))
            time.sleep(PAUSE)
    out = ["", "## Інформагентства", "",
           "| Агентство | Домен | У GDELT | Примітка |", "|---|---|---|---|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    path = ROOT / "gdelt-coverage.md"
    prev = path.read_text(encoding="utf-8") if path.exists() else "# Покриття GDELT\n"
    path.write_text(prev + "\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
    probe_wires()
    probe_wires()



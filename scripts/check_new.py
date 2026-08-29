#!/usr/bin/env python3
"""
check_new.py — перевіряє лише нові або названі джерела, не чіпаючи решту.

Повний прогін по 252 виданнях триває хвилини й перезаписує feeds.json.
Коли треба перевірити п'ять свіжих джерел, це надмір. Цей скрипт бере
тільки те, що ви назвали, і за бажанням доливає результат у feeds.json.

Запуск (workflow «Перевірити нові джерела»):
    python scripts/check_new.py                 # усе, чого ще немає у feeds.json
    python scripts/check_new.py --names "Bild,taz,Blick"
    python scripts/check_new.py --merge          # ще й долити у feeds.json

Пише: new-sources-report.md
"""

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover as D          # використовуємо ту саму логіку пошуку стрічки

ROOT = Path(__file__).resolve().parent.parent


def load_registry():
    return list(csv.DictReader((ROOT / "sources.csv").open(encoding="utf-8")))


def load_feeds():
    p = ROOT / "feeds.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def known_failed():
    """Видання, які вже перевірялись і не далися. Вони теж відсутні
    у feeds.json, тому без цього списку «нові» означало б «усі, що
    колись впали» — а це десятки старих джерел."""
    p = ROOT / "feed-report.md"
    if not p.exists():
        return set()
    out = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("|") and "---" not in line and "Країна" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) > 1:
                out.add(cells[1])
    return out


def pick(rows, names, include_failed=False):
    if names:
        want = {n.strip().lower() for n in names.split(",") if n.strip()}
        chosen = [r for r in rows if r["name"].lower() in want]
        missing = want - {r["name"].lower() for r in chosen}
        if missing:
            print(f"Немає в реєстрі: {', '.join(sorted(missing))}")
        return chosen

    known = {f["name"] for f in load_feeds()}
    failed = set() if include_failed else known_failed()
    fresh = [r for r in rows if r["name"] not in known and r["name"] not in failed]
    if failed:
        skipped = sum(1 for r in rows if r["name"] in failed and r["name"] not in known)
        print(f"Пропускаю {skipped} джерел, які вже перевірялись і не далися "
              f"(--retry-failed щоб узяти й їх)")
    return fresh


async def run(rows):
    limits = D.httpx.Limits(max_connections=6, max_keepalive_connections=3)
    results = []
    async with D.httpx.AsyncClient(headers=D.HEADERS, timeout=D.TIMEOUT,
                                   limits=limits,
                                   transport=D.make_transport()) as client:
        for row in rows:
            res = await D.find_feed(client, row)
            mark = {"ok": "OK  ", "failed": "FAIL", "unreachable": "DEAD"}[res["status"]]
            extra = res.get("feed") or res.get("error", "")
            print(f"{mark} {res['country']:<12} {res['name']:<22} {str(extra)[:70]}",
                  flush=True)
            results.append(res)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--names", default="", help="назви через кому")
    ap.add_argument("--retry-failed", action="store_true",
                    help="узяти й ті, що раніше не далися")
    ap.add_argument("--merge", action="store_true",
                    help="долити живі стрічки у feeds.json")
    args = ap.parse_args()

    rows = pick(load_registry(), args.names, args.retry_failed)
    if not rows:
        print("Нових джерел немає — усе вже у feeds.json")
        return

    print(f"Перевіряю {len(rows)} джерел\n")
    results = asyncio.run(run(rows))
    live = [r for r in results if r["status"] == "ok"]
    dead = [r for r in results if r["status"] != "ok"]

    lines = [
        "# Перевірка нових джерел", "",
        f"- Перевірено: **{len(results)}**",
        f"- Живих: **{len(live)}**",
        f"- Не вдалося: **{len(dead)}**", "",
        "| Країна | Видання | Стрічка або причина |", "|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r['country']} | {r['name']} | "
                     f"{r.get('feed') or r.get('error','')} |")
    (ROOT / "new-sources-report.md").write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")

    if args.merge and live:
        feeds = load_feeds()
        by_name = {f["name"]: f for f in feeds}
        for r in live:
            by_name[r["name"]] = r
        merged = list(by_name.values())
        (ROOT / "feeds.json").write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nfeeds.json оновлено: було {len(feeds)}, стало {len(merged)}")

    print(f"\nЖивих {len(live)} із {len(results)}. Звіт: new-sources-report.md")


if __name__ == "__main__":
    main()

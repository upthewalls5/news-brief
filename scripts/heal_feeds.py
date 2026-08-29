#!/usr/bin/env python3
"""
heal_feeds.py — сам піднімає стрічки, які перестали відповідати.

Стрічки помирають тихо: сайт переїжджає, змінює CMS, прибирає розділ.
Повна перевірка ловить це раз на тиждень, а до неї джерело просто мовчить,
і бріф поступово біднішає непомітно.

Логіка проста. collect.py щодня записує, хто не відповів. Скрипт веде
лічильник поспіль. Коли джерело мовчить кілька днів підряд, він шукає
для нього нову адресу тим самим механізмом, що й повна перевірка, і в разі
успіху оновлює feeds.json.

Перевідкриваємо не одразу, а після кількох днів: одноденний збій буває
через тимчасові проблеми сайту, і бігати за ним щоразу немає сенсу.

Читає:  state/last-dead.json, state/feed-health.json, sources.csv, feeds.json
Пише:   state/feed-health.json, feeds.json, heal-report.md
"""

import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover as D

ROOT = Path(__file__).resolve().parent.parent

FAILS_BEFORE_HEAL = 3     # днів мовчання, після яких шукаємо нову адресу
GIVE_UP_AFTER = 21        # днів, після яких визнаємо джерело втраченим
MAX_PER_RUN = 12          # скільки лікуємо за раз, щоб не розтягувати збір


def load(path, default):
    p = ROOT / path
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def main():
    last = load("state/last-dead.json", {})
    if not last:
        print("Немає даних про вчорашній збір, лікувати нічого")
        return

    health = load("state/feed-health.json", {})
    today = datetime.now(timezone.utc).date().isoformat()
    dead = set(last.get("dead", []))
    alive = set(last.get("alive", []))

    for name in alive:
        if name in health:
            health.pop(name)
    for name in dead:
        rec = health.setdefault(name, {"fails": 0, "since": today})
        rec["fails"] += 1
        rec["last"] = today

    sick = sorted((n for n, r in health.items()
                   if FAILS_BEFORE_HEAL <= r["fails"] < GIVE_UP_AFTER),
                  key=lambda n: -health[n]["fails"])[:MAX_PER_RUN]
    lost = [n for n, r in health.items() if r["fails"] >= GIVE_UP_AFTER]

    print(f"Мовчать: {len(dead)} | до лікування: {len(sick)} | "
          f"втрачені: {len(lost)}")

    healed = []
    if sick:
        rows = {r["name"]: r for r in
                csv.DictReader((ROOT / "sources.csv").open(encoding="utf-8"))}
        targets = [rows[n] for n in sick if n in rows]

        async def run():
            limits = D.httpx.Limits(max_connections=10, max_keepalive_connections=5)
            sem = asyncio.Semaphore(6)
            out = []

            async def one(row):
                async with sem:
                    try:
                        return await asyncio.wait_for(
                            D.find_feed(client, row), timeout=45)
                    except asyncio.TimeoutError:
                        return {"name": row["name"], "status": "failed"}

            async with D.httpx.AsyncClient(headers=D.HEADERS, timeout=D.TIMEOUT,
                                           limits=limits,
                                           transport=D.make_transport()) as client:
                out = await asyncio.gather(*(one(r) for r in targets))
            return out

        results = asyncio.run(run())
        feeds = load("feeds.json", [])
        by_name = {f["name"]: f for f in feeds}
        for res in results:
            if res.get("status") == "ok":
                old = by_name.get(res["name"], {}).get("feed", "")
                by_name[res["name"]] = res
                health.pop(res["name"], None)
                healed.append((res["name"], old, res["feed"]))
                print(f"  піднято: {res['name']} → {res['feed']}", flush=True)
            else:
                print(f"  не вдалось: {res.get('name')}", flush=True)
        if healed:
            (ROOT / "feeds.json").write_text(
                json.dumps(list(by_name.values()), ensure_ascii=False, indent=2),
                encoding="utf-8")

    (ROOT / "state").mkdir(exist_ok=True)
    (ROOT / "state" / "feed-health.json").write_text(
        json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# Стан стрічок · {today}", "",
             f"- Мовчали в останньому зборі: **{len(dead)}**",
             f"- Піднято автоматично: **{len(healed)}**",
             f"- Втрачені (мовчать понад {GIVE_UP_AFTER} днів): **{len(lost)}**", ""]
    if healed:
        lines += ["## Піднято", "", "| Видання | Була | Стала |", "|---|---|---|"]
        lines += [f"| {n} | {o or '—'} | {f} |" for n, o, f in healed]
        lines.append("")
    if lost:
        lines += ["## Втрачені — потрібна ручна заміна", ""]
        lines += [f"- {n} (мовчить {health[n]['fails']} днів)" for n in sorted(lost)]
    (ROOT / "heal-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Піднято {len(healed)}, втрачених {len(lost)}. Звіт: heal-report.md")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
shorten_issue.py — стисла версія випуску для Telegraph.

Telegraph тримає близько 20 КБ, тобто вчетверо менше, ніж займає повний
випуск українською. Раніше ми викидали цілі рубрики, і сторінка ставала
не стислою версією, а уривком.

Тут інакше: усі рубрики лишаються, скорочується зміст кожної. Механічно
це зробити не можна — обрізати думку посеред речення гірше, ніж її
переказати. Тому один короткий запит до моделі.

Читає:  issues/YYYY-MM-DD.md, prompts/shorten.md
Пише:   issues/short-YYYY-MM-DD.md
Потрібен секрет: ANTHROPIC_API_KEY
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from write import call_api

ROOT = Path(__file__).resolve().parent.parent
MAX_TOKENS = 8000
TARGET = 4200          # запас над орієнтиром у промпті


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("Немає ANTHROPIC_API_KEY, стислу версію пропускаю")
        return

    iso = datetime.now(timezone.utc).date().isoformat()
    src = ROOT / "issues" / f"{iso}.md"
    if not src.exists():
        print("Немає випуску за сьогодні")
        return

    system = (ROOT / "prompts" / "shorten.md")
    if not system.exists():
        print("Немає prompts/shorten.md")
        return

    full = src.read_text(encoding="utf-8").strip()
    print(f"Скорочую {len(full)} символів...")
    short = call_api(key, system.read_text(encoding="utf-8"),
                     f"ПОВНИЙ ВИПУСК:\n{full}", MAX_TOKENS)

    if not short:
        print("Модель нічого не повернула")
        return
    short = short.strip()

    # Запобіжники: занадто коротка версія означає, що модель щось зрозуміла
    # не так, занадто довга не влізе на сторінку.
    # Поріг відносний: у тихий день і повний випуск коротший.
    floor = max(600, int(len(full) * 0.08))
    if len(short) < floor:
        print(f"Стисла версія підозріло коротка ({len(short)} проти "
              f"мінімуму {floor}), пропускаю")
        return
    if len(short) > TARGET * 1.8:
        print(f"Стисла версія завелика ({len(short)}), пропускаю — "
              "publish.py скоротить механічно")
        return

    (ROOT / "issues" / f"short-{iso}.md").write_text(short + "\n", encoding="utf-8")
    print(f"Стисла версія: {len(short)} символів "
          f"({len(full) / max(1, len(short)):.1f}× коротше)")


if __name__ == "__main__":
    main()

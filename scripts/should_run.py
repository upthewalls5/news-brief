#!/usr/bin/env python3
"""
should_run.py — вирішує, чи робити випуск у цьому запуску.

Розклад GitHub ненадійний, тому воркфлоу стартує кілька разів за ранок.
Перша спроба, яка дійде, робить бріф. Решта бачать, що випуск за сьогодні
вже надіслано, і виходять, нічого не витрачаючи.

Ручний запуск працює завжди: якщо ви натиснули Run workflow, значить
випуск потрібен незалежно від того, що вже було.

Пише в GITHUB_OUTPUT рядок run=yes або run=no.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def decide():
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return True, "ручний запуск — робимо завжди"

    iso = datetime.now(timezone.utc).date().isoformat()
    issue = ROOT / "issues" / f"{iso}.md"
    if not issue.exists():
        return True, "випуску за сьогодні ще немає"

    # Файл є, але чи він справді сьогоднішній? Перевіряємо мітку доставки:
    # без неї бріф міг лишитись від невдалого запуску.
    sent = ROOT / "state" / "last-write.txt"
    if not sent.exists():
        return True, "випуск є, але позначки про доставку немає"

    try:
        stamp = datetime.fromisoformat(sent.read_text(encoding="utf-8").strip())
    except Exception:
        return True, "позначка нечитабельна"

    if stamp.date().isoformat() != iso:
        return True, "позначка від іншого дня"

    hours = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
    return False, f"бріф за сьогодні вже зроблено {hours:.1f} год тому"


def main():
    run, why = decide()
    print(f"{'Робимо випуск' if run else 'Пропускаємо'}: {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'yes' if run else 'no'}\n")


if __name__ == "__main__":
    main()

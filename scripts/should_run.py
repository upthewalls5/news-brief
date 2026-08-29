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
    # Зовнішній тригер приходить як workflow_dispatch, але з source=cron.
    # Для нього захист від дубля потрібен так само, як для розкладу:
    # інакше кілька спроб дали б кілька брифів за ранок.
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    source = os.environ.get("TRIGGER_SOURCE", "manual").strip().lower()
    if event == "workflow_dispatch" and source != "cron":
        return True, "ручний запуск з інтерфейсу — робимо завжди"

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
    src = os.environ.get("TRIGGER_SOURCE", "manual")
    print(f"Тригер: {os.environ.get('GITHUB_EVENT_NAME','?')} (source={src})")
    print(f"{'Робимо випуск' if run else 'Пропускаємо'}: {why}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"run={'yes' if run else 'no'}\n")


if __name__ == "__main__":
    main()

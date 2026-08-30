#!/usr/bin/env python3
"""
review.py — два редактори перевіряють випуск перед відправкою.

Перший читає на предмет фактів: атрибуція спірного, одноджерельні
твердження, дублі, країни не на своєму місці. Другий — на предмет подачі:
чи різні голоси в рубрик, чи не порожні прогнози, чи є справжні причинні
зв'язки. Далі третій прохід переписує випуск за їхніми зауваженнями.

Про «автонавчання» чесно: модель не запам'ятовує нічого між запусками.
Але накопичувати можна ЗАУВАЖЕННЯ. Редактори виносять з кожного випуску
кілька уроків, вони лягають у state/lessons.md, а той файл потрапляє в
промпт наступного дня. Це не навчання моделі, а пам'ять редакції — і
працює вона так само: наступний випуск пишеться з оглядкою на попередні
помилки.

Читає:  issues/YYYY-MM-DD.md, prompts/review-facts.md, prompts/review-craft.md
Пише:   issues/YYYY-MM-DD.md (виправлений), review-report.md,
        state/lessons.md
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from write import call_api                # той самий потоковий клієнт

ROOT = Path(__file__).resolve().parent.parent
MAX_REVIEW = 6000
MAX_REVISION = 20000
LESSONS_CAP = 4000


def read(path, default=""):
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.exists() else default


def split_notes(text):
    """Ділить відповідь редактора на зауваження і уроки."""
    if "===УРОКИ===" not in text:
        return text.strip(), ""
    notes, lessons = text.split("===УРОКИ===", 1)
    return notes.replace("===ЗАУВАЖЕННЯ===", "").strip(), lessons.strip()


def merge_lessons(old, fresh):
    """Уроки накопичуються, але не нескінченно: старі витісняються новими,
    дублікати відкидаються за першими словами."""
    lines = [l.strip().lstrip("-•— ").strip()
             for l in (fresh + "\n" + old).split("\n")]
    out, seen = [], set()
    for l in lines:
        if len(l) < 12 or l.startswith("#"):
            continue
        key = " ".join(l.lower().split()[:5])
        if key in seen:
            continue
        seen.add(key)
        out.append(f"- {l}")
        if sum(len(x) for x in out) > LESSONS_CAP:
            break
    return "# Уроки редакторів\n\n" + "\n".join(out) + "\n"


def main():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("Немає ANTHROPIC_API_KEY, перевірку пропускаю")
        return

    iso = datetime.now(timezone.utc).date().isoformat()
    path = ROOT / "issues" / f"{iso}.md"
    if not path.exists():
        print("Немає випуску за сьогодні, перевіряти нічого")
        return

    issue = path.read_text(encoding="utf-8").strip()
    context = (f"ПАМ'ЯТЬ:\n{read('state/threads.md')}\n\n"
               f"НАШІ ПРОГНОЗИ:\n{read('state/predictions.md')[:2500]}\n\n"
               f"УРОКИ ПОПЕРЕДНІХ ВИПУСКІВ:\n{read('state/lessons.md')}")

    reports, lessons_new = [], []
    for name, prompt_file in (("фактів", "review-facts.md"),
                              ("подачі", "review-craft.md")):
        system = read(f"prompts/{prompt_file}")
        if not system:
            print(f"Немає prompts/{prompt_file}, редактора {name} пропускаю")
            continue
        print(f"Редактор {name}...")
        out = call_api(key, system, f"{context}\n\nВИПУСК:\n{issue}", MAX_REVIEW)
        notes, lessons = split_notes(out or "")
        if notes:
            reports.append((name, notes))
        if lessons:
            lessons_new.append(lessons)
        print(f"  зауважень: {len(notes.splitlines())} рядків")

    if not reports:
        print("Редактори нічого не повернули, лишаю випуск як є")
        return

    joined = "\n\n".join(f"РЕДАКТОР {n.upper()}:\n{t}" for n, t in reports)
    fix_prompt = read("prompts/review-fix.md")
    if not fix_prompt:
        print("Немає prompts/review-fix.md, правку пропускаю")
    else:
        print("Правка за зауваженнями...")
        fixed = call_api(key, fix_prompt,
                         f"ЗАУВАЖЕННЯ РЕДАКТОРІВ:\n{joined}\n\n"
                         f"ВИПУСК:\n{issue}", MAX_REVISION)
        if fixed and len(fixed) > len(issue) * 0.6:
            path.write_text(fixed.strip() + "\n", encoding="utf-8")
            (ROOT / "issues" / "latest.md").write_text(
                fixed.strip() + "\n", encoding="utf-8")
            print(f"Випуск виправлено: {len(issue)} → {len(fixed)} символів")
        else:
            print("Правка підозріло коротка, лишаю оригінал")

    if lessons_new:
        merged = merge_lessons(read("state/lessons.md"),
                               "\n".join(lessons_new))
        (ROOT / "state").mkdir(exist_ok=True)
        (ROOT / "state" / "lessons.md").write_text(merged, encoding="utf-8")
        print(f"Уроків у файлі: {merged.count(chr(10) + '-')}")

    (ROOT / "review-report.md").write_text(
        f"# Зауваження редакторів · {iso}\n\n{joined}\n", encoding="utf-8")


if __name__ == "__main__":
    main()

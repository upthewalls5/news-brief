#!/usr/bin/env python3
"""
send.py — відправляє готовий бріф у Telegram.

Читає:  issues/latest.md
Потрібні секрети: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

Надсилає звичайним текстом без розмітки. Це навмисно: Telegram суворий до
markdown і повертає помилку 400 на будь-який неекранований символ. Емодзі,
переноси й відступи в звичайному тексті працюють, а зламатись нема чому.

Повідомлення довші за 4096 символів ріжуться по порожньому рядку.
"""

import os
import sys
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
VERSION = "2026-08-28.16"
LIMIT = 3400   # запас під теги розмітки  # запас до телеграмівських 4096


# ── Оформлення для Telegram ────────────────────────────────────────────
# Розмітку робимо тут, а не в моделі: модель рано чи пізно зламає тег,
# і Telegram відповість 400 на весь випуск. Тут же ми спершу екрануємо
# геть усе, а потім вставляємо власні теги за структурою випуску.

RUBRIC = "🌍🔀📍💰🕳📡🧭📖⚠"

# Прапор (дві регіональні літери) + назва + двокрапка: країна або видання
FLAG_LINE = re.compile(
    r"^([\U0001F1E6-\U0001F1FF]{2})\s*([^:]{2,48}):\s*(.*)$")

LABELS = ("Замовчують:", "Чому розходяться:", "Не відповіли:", "Не відповіли (")


def esc(t: str) -> str:
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def decorate(text: str) -> str:
    """Плаский текст випуску -> HTML для Telegram."""
    out = []
    for raw in text.split("\n"):
        line = esc(raw.rstrip())
        stripped = line.lstrip()

        if not stripped:
            out.append("")
            continue

        # Заголовок рубрики — жирним, з відступом зверху
        if stripped[0] in RUBRIC:
            body = stripped.lstrip("".join(RUBRIC)).strip()
            if body and body == body.upper():
                if out and out[-1] != "":
                    out.append("")
                out.append(f"<b>{stripped[0]} {body}</b>")
                continue

        # Країна або видання: прапор + назва жирним
        m = FLAG_LINE.match(stripped)
        if m:
            flag, name, rest = m.groups()
            out.append(f"{flag} <b>{name.strip()}:</b> {rest}")
            continue

        # Службові підписи всередині «Розколу оптики»
        for lab in LABELS:
            if stripped.startswith(lab):
                out.append(f"<i>{stripped}</i>")
                break
        else:
            out.append(line)

    return "\n".join(out)


def read_hook():
    """Гачки, згенеровані разом із випуском."""
    iso = datetime.now(timezone.utc).date().isoformat()
    p = ROOT / "issues" / f"hook-{iso}.txt"
    if not p.exists():
        return []
    lines = [l.strip().lstrip("-•—").strip()
             for l in p.read_text(encoding="utf-8").splitlines()]
    return [l for l in lines if len(l) > 12][:3]


def read_greeting():
    iso = datetime.now(timezone.utc).date().isoformat()
    p = ROOT / "issues" / f"greet-{iso}.txt"
    if p.exists():
        g = p.read_text(encoding="utf-8").strip().split("\n")[0][:60]
        if len(g) > 4:
            return g
    return "Доброго ранку"


def header() -> str:
    """Привітання під настрій дня плюс дата з роком. Розмітку навісить
    send() після екранування — інакше decorate() екранує наші ж теги."""
    months = ("січня", "лютого", "березня", "квітня", "травня", "червня",
              "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")
    now = datetime.now(timezone.utc)
    return (f"{read_greeting()} · "
            f"{now.day} {months[now.month - 1]} {now.year}")


# ── Коротка версія для повідомлення ────────────────────────────────────
# Повний випуск живе на telegra.ph. У Telegram іде верхівка: те, що має
# бути видно зі сповіщення без жодного тапу.

# У повідомлення йдуть лише гачки й ГОЛОВНЕ, по одному реченню на пункт.
# Решта — на telegra.ph. Мета: щоб усе було видно зі сповіщення без гортання.

RUBRIC_CHARS = "🌍🔀📍💰🗞🕳📡🔮🧭📖"
FIRST_SENTENCE = re.compile(r"^(.+?[.!?…])(\s|$)")



DAY_TAG = re.compile(r"^(день)\s+(\d+)\s*[:—-]\s*(.)", re.I)


def normalize(line: str) -> str:
    """Позначка дня має виглядати однаково незалежно від того, як її
    написала модель: «День 4 — Текст»."""
    m = DAY_TAG.match(line.strip())
    if m:
        return f"День {m.group(2)} — {m.group(3).upper()}" + line.strip()[m.end():]
    return line

def first_sentence(line: str) -> str:
    """Перше речення пункту. У ГОЛОВНОМУ їх два: подія і наслідок —
    для сповіщення лишаємо подію."""
    line = line.strip()
    m = FIRST_SENTENCE.match(line)
    text = normalize(m.group(1).strip() if m else line)
    if len(text) > 150:
        cut = text[:150]
        # Ріжемо по комі або тире, якщо вони є в останній третині —
        # так речення обривається на природній паузі, а не на сполучнику.
        for sep in ("; ", ", ", " — "):
            i = cut.rfind(sep, 90)
            if i > 0:
                cut = cut[:i]
                break
        else:
            cut = cut.rsplit(" ", 1)[0]
        # Огризки на кшталт «а», «і», «та» в кінці виглядають зламано
        words = cut.rstrip(" ,;—").split()
        while words and words[-1].lower() in (
                "а", "і", "й", "та", "але", "що", "як", "де", "коли",
                "бо", "чи", "до", "на", "у", "в", "з", "із", "за", "по"):
            words.pop()
        text = " ".join(words).rstrip(" ,;—") + "…"
    return text


def shorten(text: str, limit: int = 600, max_points: int = 3) -> str:
    """Лишає тільки блок ГОЛОВНЕ, стиснутий до одного речення на пункт."""
    lines, inside = [], False
    for raw in text.split("\n"):
        stripped = raw.strip()
        if stripped and stripped[0] in RUBRIC_CHARS:
            if inside:
                break
            inside = stripped[0] == "🌍"
            continue
        if not inside or not stripped:
            continue
        if stripped.startswith("Джерела:"):
            continue
        lines.append(first_sentence(stripped))

    out = []
    for l in lines[:max_points]:
        if sum(len(x) + 3 for x in out) + len(l) > limit:
            break
        out.append(l)
    if not out:
        return text[:limit]
    return "\n\n".join(f"• {l}" for l in out)


def read_link():
    iso = datetime.now(timezone.utc).date().isoformat()
    p = ROOT / "issues" / f"link-{iso}.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def split_message(text: str):
    if len(text) <= LIMIT:
        return [text]
    parts, current = [], ""
    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 > LIMIT:
            if current:
                parts.append(current.strip())
            # окремий блок сам по собі завеликий — ріжемо по рядках
            while len(block) > LIMIT:
                cut = block.rfind("\n", 0, LIMIT)
                cut = cut if cut > 0 else LIMIT
                parts.append(block[:cut].strip())
                block = block[cut:]
            current = block
        else:
            current = f"{current}\n\n{block}" if current else block
    if current.strip():
        parts.append(current.strip())
    return parts


def preview_path():
    iso = datetime.now(timezone.utc).date().isoformat()
    p = ROOT / "charts" / f"preview-{iso}.png"
    return p if p.exists() else None


def send_photo(token, chat_id, path, caption):
    """Картка з підписом. Ліміт підпису Telegram — 1024 символи."""
    with httpx.Client(timeout=90.0) as client:
        with open(path, "rb") as fh:
            r = client.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption[:1024],
                      "parse_mode": "HTML"},
                files={"photo": (path.name, fh, "image/png")})
    if r.status_code >= 400:
        raise RuntimeError(f"Telegram sendPhoto {r.status_code}: {r.text[:200]}")


def _post(token, payload):
    with httpx.Client(timeout=40.0) as client:
        return client.post(
            f"https://api.telegram.org/bot{token}/sendMessage", json=payload)


def send(token, chat_id, text, top=None, html=True):
    """Пробує HTML. Якщо Telegram не прийняв розмітку — шле плаский текст,
    щоб зіпсоване оформлення ніколи не з'їдало сам випуск.
    top — шапка простим текстом, теги на неї навішуються тут."""
    base = {"chat_id": chat_id, "disable_web_page_preview": True}
    if html:
        body = decorate(text)
        if top:
            body = f"<b>{esc(top)}</b>\n\n{body}"
        r = _post(token, {**base, "text": body, "parse_mode": "HTML"})
        if r.status_code < 400:
            return
        print(f"Telegram не прийняв HTML ({r.status_code}), шлю без розмітки")
    plain = f"{top}\n\n{text}" if top else text
    r = _post(token, {**base, "text": plain})
    if r.status_code >= 400:
        raise RuntimeError(f"Telegram {r.status_code}: {r.text[:300]}")


def written_recently(minutes: int = 90) -> bool:
    """Чи писався випуск у цьому запуску. Крок написання може впасти, а
    публікація й відправка помічені if:always і відпрацюють однаково —
    без цієї перевірки вони випустили б учорашній файл ще раз."""
    p = ROOT / "state" / "last-write.txt"
    if not p.exists():
        return False
    try:
        stamp = datetime.fromisoformat(p.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    age = (datetime.now(timezone.utc) - stamp).total_seconds() / 60
    return age <= minutes


def main():
    print(f"send.py версія {VERSION}")
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        sys.exit("Немає секретів TELEGRAM_BOT_TOKEN або TELEGRAM_CHAT_ID")

    # Читаємо СЬОГОДНІШНІЙ файл, а не latest.md. Інакше при падінні кроку
    # написання пішов би вчорашній випуск, і про поломку ніхто б не дізнався.
    today = datetime.now(timezone.utc).date().isoformat()
    path = ROOT / "issues" / f"{today}.md"

    if path.exists() and written_recently():
        text = path.read_text(encoding="utf-8").strip()
        weekly = ROOT / "issues" / f"weekly-{today}.md"
        if weekly.exists():
            extra = weekly.read_text(encoding="utf-8").strip()
            text = f"{text}\n\n{'-' * 24}\n\n📅 ОГЛЯД ТИЖНЯ\n\n{extra}"
            print("Додано тижневий огляд")
    else:
        prev = sorted((ROOT / "issues").glob("20*.md")) if (ROOT / "issues").exists() else []
        last = prev[-1].stem if prev else "немає"
        text = ("⚠️ Бріф за сьогодні не сформувався.\n\n"
                "Стрічки зібрались, але крок написання випуску впав. "
                f"Останній наявний випуск: {last}.\n\n"
                "Подивіться вкладку Actions у репозиторії — там причина.")
        print(f"УВАГА: {path.name} відсутній, надсилаю повідомлення про збій")

    link = read_link()
    if link:
        # Повний випуск на telegra.ph — у повідомленні лише верхівка
        hooks = read_hook()
        intro = ("\n".join(f"→ {h}" for h in hooks) + "\n\n") if hooks else ""
        body = intro + shorten(text) + f"\n\n📄 Повний випуск: {link}"
        if hooks:
            print(f"Анонс: {len(hooks)} рядків")
        parts = split_message(body)
        print(f"Коротка версія: {len(body)} символів, посилання є")
    else:
        parts = split_message(text)
        print("Посилання немає, шлю випуск повністю")

    photo = preview_path()
    if photo and len(parts) == 1 and len(parts[0]) < 900:
        # Усе вміщується в підпис — шлемо одним повідомленням із карткою
        caption = f"<b>{esc(header())}</b>\n\n{decorate(parts[0])}"
        try:
            send_photo(token, chat_id, photo, caption)
            print(f"Відправлено карткою, {len(text)} символів")
            return
        except Exception as exc:
            print(f"Картка не пішла ({exc}), шлю текстом")

    for i, part in enumerate(parts):
        if len(parts) > 1:
            part = f"{part}\n\n({i + 1}/{len(parts)})"
        send(token, chat_id, part, top=header() if i == 0 else None)
        if i < len(parts) - 1:
            time.sleep(1)

    print(f"Відправлено {len(parts)} повідомлень, {len(text)} символів")


if __name__ == "__main__":
    main()

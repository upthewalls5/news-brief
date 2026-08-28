#!/usr/bin/env python3
"""
publish.py — публікує повний випуск на telegra.ph і повертає посилання.

Читає:  issues/YYYY-MM-DD.md, issues/weekly-YYYY-MM-DD.md
Пише:   state/telegraph.json (токен акаунта + історія посилань)
        issues/link-YYYY-MM-DD.txt (адреса для send.py)

Потрібен секрет TELEGRAPH_TOKEN. Токен НЕ зберігається у файлах: інакше він
лежав би у публічному репозиторії, і будь-хто міг би публікувати та редагувати
сторінки від вашого імені. Створюється один раз вручну (див. SETUP.md).

Оформлення: рубрики стають заголовками, полюси «Розколу оптики» —
цитатами, рядок «Джерела:» під кожною рубрикою — виноскою.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.telegra.ph"
STATE = ROOT / "state" / "telegraph.json"

MONTHS = ("січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")

RUBRIC_EMOJI = "🌍🔀📍💰🗞🕳📡🔮🧭📖📅📈📉🎯🔭"
FLAG = re.compile(r"^([\U0001F1E6-\U0001F1FF]{2})\s*([^:]{2,48}):\s*(.*)$")
URL = re.compile(r"(https?://\S+)")
LABELS = ("Замовчують:", "Чому розходяться:", "Наші:", "Кажуть інші:")


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"pages": []}


def get_token():
    """Тільки з секрету. Ніколи не створюємо акаунт на льоту й ніколи
    не пишемо токен у файл — репозиторій публічний."""
    token = os.environ.get("TELEGRAPH_TOKEN", "").strip()
    if not token:
        print("Немає секрету TELEGRAPH_TOKEN — публікацію пропускаю.")
        print("Як отримати токен, описано в SETUP.md, крок 11.")
        return None
    return token


def rich(text):
    """Текст -> вузли Telegraph. Посилання робить клікабельними."""
    nodes, last = [], 0
    for m in URL.finditer(text):
        if m.start() > last:
            nodes.append(text[last:m.start()])
        url = m.group(1).rstrip(".,;)")
        nodes.append({"tag": "a", "attrs": {"href": url}, "children": [url]})
        last = m.start() + len(url)
    if last < len(text):
        nodes.append(text[last:])
    return nodes or [text]


def build_nodes(brief, weekly=None):
    """Перетворює плаский випуск на оформлену сторінку."""
    nodes = []
    sources_all = []

    def render(body, level="h3"):
        rubric = ""
        for raw in body.split("\n"):
            line = raw.strip()
            if not line:
                continue

            # Рубрика
            if line[0] in RUBRIC_EMOJI:
                rubric = line
                nodes.append({"tag": level, "children": [line]})
                continue

            # Виноска з джерелами під рубрикою
            if line.startswith("Джерела:"):
                names = line[len("Джерела:"):].strip()
                sources_all.extend(
                    n.strip() for n in re.split(r"[,;·]", names) if n.strip())
                nodes.append({"tag": "aside", "children": [line]})
                continue

            # Прапор + назва. Цитата доречна лише в «Розколі оптики»:
            # у «Пульсі країн» двадцять цитат поспіль перевантажують сторінку.
            m = FLAG.match(line)
            if m:
                flag, name, rest = m.groups()
                inner = [f"{flag} ", {"tag": "b", "children": [f"{name.strip()}: "]}]
                inner += rich(rest)
                tag = "blockquote" if "РОЗКОЛ" in rubric else "p"
                nodes.append({"tag": tag, "children": inner})
                continue

            # Службові підписи
            if any(line.startswith(l) for l in LABELS):
                lab = line.split(":", 1)[0] + ":"
                rest = line[len(lab):].strip()
                nodes.append({"tag": "p", "children":
                              [{"tag": "i", "children": [lab + " "]}] + rich(rest)})
                continue

            nodes.append({"tag": "p", "children": rich(line)})

    render(brief)

    if weekly:
        nodes.append({"tag": "hr"})
        nodes.append({"tag": "h3", "children": ["📅 Огляд тижня"]})
        render(weekly, level="h4")

    # Підсумковий перелік джерел
    uniq = []
    for s in sources_all:
        if s not in uniq:
            uniq.append(s)
    if uniq:
        nodes.append({"tag": "hr"})
        nodes.append({"tag": "h4", "children": ["Джерела випуску"]})
        nodes.append({"tag": "p", "children": [
            f"Випуск зібрано з {len(uniq)} видань, зіставлених між собою: "
            + ", ".join(uniq) + "."]})

    nodes.append({"tag": "aside", "children": [
        "Автоматичний огляд світової преси. Порівнюються видання з протилежними "
        "редакційними позиціями; матеріали державних медіа подаються як офіційна "
        "позиція, а не як факт."]})
    return nodes


def main():
    today = datetime.now(timezone.utc).date()
    iso = today.isoformat()
    path = ROOT / "issues" / f"{iso}.md"
    if not path.exists():
        print(f"Немає {path.name}, публікувати нічого")
        return

    brief = path.read_text(encoding="utf-8").strip()
    wpath = ROOT / "issues" / f"weekly-{iso}.md"
    weekly = wpath.read_text(encoding="utf-8").strip() if wpath.exists() else None

    token = get_token()
    if not token:
        return

    state = load_state()
    title = f"Ранковий бріф · {today.day} {MONTHS[today.month - 1]}"

    with httpx.Client(timeout=60.0) as client:
        nodes = build_nodes(brief, weekly)
        r = client.post(f"{API}/createPage", json={
            "access_token": token,
            "title": title[:256],
            "author_name": "Ранковий бріф",
            "content": nodes,
            "return_content": False,
        })
        data = r.json()

    if not data.get("ok"):
        msg = str(data.get("error", data))[:200]
        if "TOKEN" in msg.upper():
            print("Telegraph не прийняв токен. Перевірте секрет TELEGRAPH_TOKEN.")
        else:
            print(f"Telegraph відмовив: {msg}")
        return

    url = data["result"]["url"]
    state = {"pages": ([{"date": iso, "url": url}] + state.get("pages", []))[:120]}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "issues" / f"link-{iso}.txt").write_text(url, encoding="utf-8")
    print(f"Опубліковано: {url}")


if __name__ == "__main__":
    main()

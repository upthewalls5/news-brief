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



# ── Візуальні елементи ─────────────────────────────────────────────────
# Дві речі, обидві з наших власних даних. Фотографії з матеріалів — чужі,
# передруковувати їх не можна, тому візуал будуємо з того, що порахували самі.

COUNTRY_HEAD = re.compile(r"^###\s+(.+?)\s+\((\d+)\s+матеріал\w*,\s*([\d.]+)%")


def read_shares(limit=12):
    d = ROOT / "digests" / "latest.md"
    if not d.exists():
        return []
    rows = []
    for line in d.read_text(encoding="utf-8").split("\n"):
        m = COUNTRY_HEAD.match(line.strip())
        if m:
            rows.append((m.group(1), int(m.group(2)), float(m.group(3))))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:limit]


def chart_url(iso):
    """Графік лежить у репозиторії; беремо його за прямою адресою.
    З'явиться на сторінці після кроку збереження в архів."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not repo or not (ROOT / "charts" / f"{iso}.png").exists():
        return None
    return f"https://raw.githubusercontent.com/{repo}/main/charts/{iso}.png"


def attention_nodes(iso):
    """Картинка плюс текстова карта. Текст лишається читабельним навіть
    якщо картинка не завантажилась."""
    rows = read_shares()
    if not rows:
        return []

    nodes = [{"tag": "h3", "children": ["📊 Карта уваги"]}]

    url = chart_url(iso)
    if url:
        nodes.append({"tag": "figure", "children": [
            {"tag": "img", "attrs": {"src": url}},
            {"tag": "figcaption", "children": [
                "Частка країни в денному обсязі матеріалів"]}]})

    top = max(r[2] for r in rows)
    lines = []
    for name, count, share in rows:
        bar = "█" * max(1, round(share / top * 22))
        lines.append(f"{name[:18]:<18} {bar} {share}%")
    nodes.append({"tag": "pre", "children": ["\n".join(lines)]})
    nodes.append({"tag": "aside", "children": [
        "Скільки місця країна зайняла в новинному потоці за добу. "
        "Висока частка означає, що в країні щось відбувається — навіть коли "
        "світові медіа цього ще не помітили."]})
    nodes.append({"tag": "hr"})
    return nodes


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


def build_nodes(brief, weekly=None, iso=None):
    """Перетворює плаский випуск на оформлену сторінку."""
    nodes = []
    sources_all = []

    # Зміст: із восьми рубрик читач одразу бачить, що всередині
    titles = [l.strip() for l in brief.split("\n")
              if l.strip() and l.strip()[0] in RUBRIC_EMOJI]
    if len(titles) > 3:
        nodes.append({"tag": "aside", "children": [" · ".join(titles)]})
        nodes.append({"tag": "hr"})

    if iso:
        nodes.extend(attention_nodes(iso))

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
    today = datetime.now(timezone.utc).date()
    iso = today.isoformat()

    if not written_recently():
        print("Свіжого випуску немає — крок написання не відпрацював. "
              "Публікацію пропускаю, щоб не випустити старий випуск удруге.")
        return

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
        nodes = build_nodes(brief, weekly, iso)
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

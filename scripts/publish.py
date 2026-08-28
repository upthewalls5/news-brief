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
import secrets
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.telegra.ph"
VERSION = "2026-08-28.7"
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

    nodes.append({"tag": "aside", "children": [
        "Скільки місця країна зайняла в новинному потоці за добу. "
        "Висока частка означає, що в країні щось відбувається — навіть коли "
        "світові медіа цього ще не помітили."]})
    nodes.append({"tag": "hr"})
    return nodes


CAL_LINE = re.compile(r"^\[(\d{4}-\d{2}-\d{2})(?:\s*→\s*(\d{4}-\d{2}-\d{2}))?\]\s*(.+)$")
MONTHS_GEN = ("січня", "лютого", "березня", "квітня", "травня", "червня",
              "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")


def human_date(iso):
    try:
        d = datetime.fromisoformat(iso).date()
    except Exception:
        return iso
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def calendar_nodes():
    """Календар майбутніх подій: що формуватиме контекст найближчих новин."""
    p = ROOT / "state" / "calendar.md"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8").split("\n"):
        m = CAL_LINE.match(line.strip())
        if m:
            rows.append((m.group(1), m.group(2), m.group(3).strip()))
    if not rows:
        return []
    rows.sort(key=lambda r: r[0])

    nodes = [{"tag": "h3", "children": ["🗓 Календар подій попереду"]}]

    iso_today = datetime.now(timezone.utc).date().isoformat()
    img = ROOT / "charts" / f"calendar-{iso_today}.png"
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo and img.exists():
        nodes.append({"tag": "figure", "children": [
            {"tag": "img", "attrs": {"src":
                f"https://raw.githubusercontent.com/{repo}/main/charts/{img.name}"}},
            {"tag": "figcaption", "children": [
                "Підсвічені дати — події, навколо яких формуватиметься "
                "новинний потік"]}]})
    for start, end, body in rows[:20]:
        when = human_date(start)
        if end:
            when += f" → {human_date(end)}"
        nodes.append({"tag": "p", "children": [
            {"tag": "b", "children": [when + " · "]}] + rich(body)})
    nodes.append({"tag": "aside", "children": [
        "Дати, навколо яких формуватиметься новинний потік найближчих тижнів. "
        "Береться лише те, що прямо названо в матеріалах випусків."]})
    nodes.append({"tag": "hr"})
    return nodes


# Ліміт Telegraph не документований, і будь-яке вгадане число або ріже
# зайве, або не проходить. Тому не вгадуємо: шлемо повний вміст і, лише
# отримавши відмову, скорочуємо частками — доки не пройде.
SHRINK_STEPS = (1.0, 0.82, 0.68, 0.55, 0.42, 0.3)


def content_size(nodes):
    return len(json.dumps(nodes, ensure_ascii=False).encode("utf-8"))


def fit_content(nodes, limit):
    """Відкидає вузли з кінця, поки сторінка не влізе. З кінця — бо там
    найменш важливе: посилання й службові виноски."""
    if content_size(nodes) <= limit:
        return nodes
    keep = list(nodes)
    while keep and content_size(keep) > limit and len(keep) > 8:
        keep.pop()
    print(f"Вміст обрізано: {len(nodes)} → {len(keep)} вузлів, "
          f"{content_size(keep)} байт")
    return keep


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

    # Графік не дублюємо: він уже є на картці, яка приходить у Telegram.
    nodes.extend(calendar_nodes())

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
    print(f"publish.py версія {VERSION}")
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
    # Адреса на telegra.ph утворюється із заголовка, тому «бріф + дата» легко
    # вгадується. Додаємо випадковий хвіст: сторінка лишається публічною,
    # але знайти її перебором дат уже не вийде.
    # Окрема назва: раніше цей рядок затирав змінну token із токеном
    # Telegraph, і в API летів шестисимвольний хвіст замість ключа.
    slug = secrets.token_hex(3)
    title = f"Бріф {today.day} {MONTHS[today.month - 1]} {today.year} {slug}"[:200]

    with httpx.Client(timeout=60.0) as client:
        nodes = build_nodes(brief, weekly, iso)
        full = list(nodes)
        data = {}
        for step in SHRINK_STEPS:
            attempt = full if step == 1.0 else full[:max(8, int(len(full) * step))]
            r = client.post(f"{API}/createPage", json={
                "access_token": token,
                "title": title[:256],
                "author_name": "Ранковий бріф",
                "content": attempt,
                "return_content": False,
            })
            data = r.json()
            if data.get("ok"):
                if step < 1.0:
                    print(f"Вміст скорочено до {len(attempt)} зі {len(full)} "
                          f"вузлів ({content_size(attempt)} байт)")
                break
            if "CONTENT_TOO_BIG" not in str(data).upper():
                break
            print(f"Завеликий вміст на {len(attempt)} вузлах, пробую менше")

    if not data.get("ok"):
        # Друкуємо ТЕ, ЩО відповів Telegraph, а не здогад про причину.
        err = str(data.get("error", data))
        print(f"Telegraph відмовив: {err[:300]}")
        print(f"  заголовок: {len(title)} символів | вузлів: {len(nodes)}")
        hints = {
            "TITLE": "заголовок задовгий або порожній",
            "CONTENT": "неприпустимий вузол або завеликий вміст",
            "TOKEN": "проблема з токеном",
            "FLOOD": "забагато запитів поспіль",
        }
        for k, v in hints.items():
            if k in err.upper():
                print(f"  схоже на: {v}")
        return

    url = data["result"]["url"]
    state = {"pages": ([{"date": iso, "url": url}] + state.get("pages", []))[:120]}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "issues" / f"link-{iso}.txt").write_text(url, encoding="utf-8")
    print(f"Опубліковано: {url}")


if __name__ == "__main__":
    main()

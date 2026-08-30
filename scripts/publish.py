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
VERSION = "2026-08-30.5"
STATE = ROOT / "state" / "telegraph.json"

SHRINK_STEPS = (1.0, 0.82, 0.68, 0.55, 0.42, 0.3)

# Telegraph приймає приблизно 20,6 КБ — це близько 10 тисяч символів
# українською. Повний випуск удвічі більший, тому сюди йде стисла версія:
# аналітичне ядро без переліків. Усе решта — на сайті.
TELEGRAPH_RUBRICS = ("ГОЛОВНЕ", "РОЗКОЛ ОПТИКИ", "ЩО З ЧОГО ВИПЛИВАЄ",
                     "УКРАЇНСЬКИЙ ВИМІР", "ПРОГНОЗИ")


def condense(brief, keep=TELEGRAPH_RUBRICS):
    """Лишає тільки названі рубрики. Решта — ПУЛЬС КРАЇН, ГРОШІ, МАСОВА
    ОПТИКА, СЛІПА ЗОНА, РАДАР, ЩО ПОПЕРЕДУ — живуть у повній версії."""
    out, take = [], False
    for raw in brief.split("\n"):
        line = raw.strip()
        if line and line[0] in RUBRIC_EMOJI and line[1:].strip().isupper():
            take = any(k in line for k in keep)
        if take:
            out.append(raw)
    return "\n".join(out).strip() or brief
LIMIT_TIGHT = 13000

MONTHS = ("січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")

RUBRIC_EMOJI = "🌍🔀🔗📍💰🗞🕳📡🔮🗓🧭📖📅📈📉🎯🔭"
FLAG = re.compile(r"^([\U0001F1E6-\U0001F1FF]{2})\s*([^:]{2,48}):\s*(.*)$")
# У «Розколі оптики» полюсом може бути не країна, а глобальне видання —
# тоді перед назвою стоїть звичайне емодзі, а не прапор.
POLE = re.compile(r"^([^\w\s\d.,;:!?()\[\]«»\"'-])\s+([^:]{2,48}):\s*(.*)$")
# Модель часто пише країну без прапора: «Україна: …». Такий рядок теж має
# отримати жирну назву, інакше «Пульс країн» читається суцільною стіною.
NAMED = re.compile(r"^([A-ZА-ЯЄІЇҐ][^:]{1,28}):\s+(.+)$")
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


def cover_node(iso):
    """Абстрактна обкладинка над текстом випуску. Тільки абстракція:
    згенерована сцена реальної події сприймалась би як свідчення."""
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    img = ROOT / "charts" / f"cover-{iso}.png"
    if not repo or not img.exists():
        return []
    return [{"tag": "figure", "children": [
        {"tag": "img", "attrs": {"src":
            f"https://raw.githubusercontent.com/{repo}/main/charts/{img.name}"}},
        {"tag": "figcaption", "children": [
            "Абстрактна композиція за темами випуску. Згенеровано автоматично, "
            "не є зображенням реальних подій."]}]}]


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


def site_url(iso=None):
    """Адреса повної версії. Випадковий слаг веде site.py."""
    iso = iso or datetime.now(timezone.utc).date().isoformat()
    p = ROOT / "state" / "pages.json"
    if not p.exists():
        return ""
    try:
        slug = json.loads(p.read_text(encoding="utf-8")).get(iso)
    except Exception:
        return ""
    if not slug:
        return ""
    base = os.environ.get("PAGES_BASE", "").strip().rstrip("/")
    if not base:
        repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        if not repo or "/" not in repo:
            return ""
        user, name = repo.split("/", 1)
        base = f"https://{user}.github.io/{name}"
    return f"{base}/{slug}.html"


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

    if iso:
        nodes.extend(cover_node(iso))

    # Графік не дублюємо: він уже є на картці, яка приходить у Telegram.

    def render(body, level="h3"):
        rubric = ""
        for raw in body.split("\n"):
            line = raw.strip()
            if not line:
                continue

            # Рубрика: емодзі + КОРОТКА НАЗВА ВЕЛИКИМИ ЛІТЕРАМИ.
            # Без перевірки регістру рядок «🌍 Al Jazeera: …» з Розколу
            # оптики теж ставав заголовком.
            if line[0] in RUBRIC_EMOJI:
                body = line[1:].strip()
                if body and len(body) <= 40 and body == body.upper():
                    rubric = line
                    nodes.append({"tag": level, "children": [line]})
                    continue

            # Джерела збираємо, але окремими виносками під кожною рубрикою
            # більше не друкуємо: одинадцять таких блоків з'їдали помітну
            # частку ліміту сторінки, а той самий перелік є в кінці.
            if line.startswith("Джерела:"):
                names = line[len("Джерела:"):].strip()
                sources_all.extend(
                    n.strip() for n in re.split(r"[,;·]", names) if n.strip())
                continue

            # Прапор + назва. Цитата доречна лише в «Розколі оптики»:
            # у «Пульсі країн» двадцять цитат поспіль перевантажують сторінку.
            # Назва ланцюга — окремий підзаголовок. Інакше одна назва
            # ставала звичайним абзацом, а друга — жирною цитатою лише
            # тому, що в ній трапилась двокрапка.
            if "ВИПЛИВАЄ" in rubric:
                if "→" not in line and "[" not in line and len(line) < 80:
                    nodes.append({"tag": "h4", "children": [line]})
                else:
                    nodes.append({"tag": "p", "children": rich(line)})
                continue

            m = FLAG.match(line) or ("РОЗКОЛ" in rubric and POLE.match(line))
            if not m and any(k in rubric for k in ("ПУЛЬС", "РОЗКОЛ", "ГРОШІ")):
                m2 = NAMED.match(line)
                if m2:
                    name, rest = m2.groups()
                    tag = "blockquote" if "РОЗКОЛ" in rubric else "p"
                    nodes.append({"tag": tag, "children":
                                  [{"tag": "b", "children": [name + ": "]}]
                                  + rich(rest)})
                    continue
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

            # У суцільних рубриках виділяємо перше речення: у ГОЛОВНОМУ це
            # сама подія, а наслідок лишається звичайним текстом. Око чіпляється
            # за подію, а читає далі за потреби.
            if any(k in rubric for k in ("ГОЛОВНЕ", "ГРОШІ", "СЛІПА",
                                         "РАДАР", "ВИМІР")):
                m2 = re.match(r"^(.{15,110}?[.!?…])(\s+)(.+)$", line)
                if m2:
                    nodes.append({"tag": "p", "children":
                                  [{"tag": "b", "children": [m2.group(1)]}, " "]
                                  + rich(m2.group(3))})
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

    site = site_url()
    if site:
        nodes.append({"tag": "hr"})
        nodes.append({"tag": "p", "children": [
            "Це стисла версія. Повний випуск — пульс країн, гроші, масова "
            "оптика, сліпа зона, радар і календар — ",
            {"tag": "a", "attrs": {"href": site}, "children": ["на сайті"]},
            "."]})

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

    brief = condense(path.read_text(encoding="utf-8").strip())
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
    # Адреса на telegra.ph утворюється із заголовка ПРИ СТВОРЕННІ і далі
    # не змінюється. Тому створюємо під випадковою назвою, а одразу після
    # цього перейменовуємо на людську: адреса лишається невгадуваною,
    # а в заголовку немає технічного хвоста.
    tmp_title = f"b{slug}"
    title = f"Ранковий бріф · {today.day} {MONTHS[today.month - 1]} {today.year}"

    with httpx.Client(timeout=60.0) as client:
        nodes = build_nodes(brief, weekly, iso)
        full = list(nodes)
        data = {}
        for step in SHRINK_STEPS:
            if step == 1.0:
                attempt = full
            else:
                # Черга на виліт: спершу службове, текст випуску останнім.
                # Telegraph тримає приблизно 25 КБ, а кирилиця це два байти
                # на символ — тож місце під текст треба звільняти за рахунок
                # виносок і картинок, а не рубрик.
                attempt = list(full)
                if step <= 0.82:
                    attempt = [n for n in attempt
                               if not (n.get("tag") == "figure"
                                       and "cover-" in str(n))]
                if step <= 0.68:
                    attempt = [n for n in attempt if n.get("tag") != "aside"]
                if content_size(attempt) > LIMIT_TIGHT:
                    attempt = attempt[:max(8, int(len(attempt) * step))]
            r = client.post(f"{API}/createPage", json={
                "access_token": token,
                "title": tmp_title,
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
    path = data["result"].get("path")
    if path:
        with httpx.Client(timeout=60.0) as client:
            client.post(f"{API}/editPage/{path}", json={
                "access_token": token, "title": title[:256],
                "author_name": "Ранковий бріф",
                "content": data.get("_nodes") or attempt,
                "return_content": False,
            })
    state = {"pages": ([{"date": iso, "url": url}] + state.get("pages", []))[:120]}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "issues" / f"link-{iso}.txt").write_text(url, encoding="utf-8")
    print(f"Опубліковано: {url}")


if __name__ == "__main__":
    main()

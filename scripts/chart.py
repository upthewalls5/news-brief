#!/usr/bin/env python3
"""
chart.py — карта уваги дня з наших власних даних.

Це єдина картинка, яку ми маємо право публікувати: вона побудована на
тому, що порахували самі. Фотографії з матеріалів — чужі.

Читає:  digests/latest.md
Пише:   charts/YYYY-MM-DD.png
"""

import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HEAD = re.compile(r"^###\s+(.+?)\s+\((\d+)\s+матеріал\w*,\s*([\d.]+)%")
TOP = 12

INK = "#1c1c1c"
MUTED = "#8a8a8a"
BG = "#12161d"
CARD = "#1a1f28"
BAR = "#4d6b82"
MUTED = "#8b95a5"
DIM = "#5a6472"
BASE = "#2f4858"
ACCENT = "#c0442f"
HIGHLIGHT = {"Ukraine", "Україна"}

# Дайджест зберігає країни англійською — на графіку вони мають бути
# українською, бо це частина українського випуску.
UA = {
    "Ukraine": "Україна", "USA": "США", "Russia": "росія", "China": "Китай",
    "Germany": "Німеччина", "France": "Франція", "UK": "Британія",
    "Poland": "Польща", "Israel": "Ізраїль", "Iran": "Іран", "India": "Індія",
    "Taiwan": "Тайвань", "Japan": "Японія", "South Korea": "Корея",
    "Italy": "Італія", "Spain": "Іспанія", "Turkey": "Туреччина",
    "Brazil": "Бразилія", "Mexico": "Мексика", "Argentina": "Аргентина",
    "Australia": "Австралія", "Kazakhstan": "Казахстан", "Belarus": "Білорусь",
    "Netherlands": "Нідерланди", "Belgium": "Бельгія", "Austria": "Австрія",
    "Switzerland": "Швейцарія", "Sweden": "Швеція", "Norway": "Норвегія",
    "Denmark": "Данія", "Finland": "Фінляндія", "Portugal": "Португалія",
    "Ireland": "Ірландія", "Greece": "Греція", "Czechia": "Чехія",
    "Slovakia": "Словаччина", "Hungary": "Угорщина", "Romania": "Румунія",
    "Bulgaria": "Болгарія", "Croatia": "Хорватія", "Serbia": "Сербія",
    "Slovenia": "Словенія", "Estonia": "Естонія", "Latvia": "Латвія",
    "Lithuania": "Литва", "Moldova": "Молдова", "Bosnia": "Боснія",
    "Iceland": "Ісландія", "UAE": "ОАЕ", "EU-Brussels": "Брюссель",
    "Global": "Світові агенції",
}


def parse(text):
    rows = []
    for line in text.split("\n"):
        m = HEAD.match(line.strip())
        if m:
            rows.append((m.group(1), int(m.group(2)), float(m.group(3))))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows


def main():
    digest = ROOT / "digests" / "latest.md"
    if not digest.exists():
        print("Немає дайджесту, графік не малюю")
        return

    all_rows = parse(digest.read_text(encoding="utf-8"))
    if len(all_rows) < 5:
        print(f"Країн замало ({len(all_rows)}), графік не малюю")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception as exc:
        print(f"matplotlib недоступний ({exc}), графік пропускаю")
        return

    rows = all_rows[:8]
    total_items = sum(r[1] for r in all_rows)
    top = rows[0][2]
    today = datetime.now(timezone.utc).date()

    # Та сама смужка, що на картці в Telegram: відсоток згори, брусок,
    # назва знизу. Стовпчикова діаграма займала пів екрана й повторювала
    # те саме кількома способами.
    W, H = 12.0, 1.75
    fig = plt.figure(figsize=(W, H), dpi=170)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.add_patch(Rectangle((0.18, 0.16), W - 0.36, H - 0.32,
                           facecolor=CARD, edgecolor="none"))
    ax.add_patch(Rectangle((0.18, 0.16), 0.06, H - 0.32,
                           facecolor=ACCENT, edgecolor="none"))

    x, right = 0.62, W - 0.62
    ax.text(x, H - 0.38, "УВАГА ПРЕСИ ЗА ДОБУ", fontsize=10.5, color=DIM,
            fontweight="bold", va="top")
    ax.text(right, H - 0.38,
            f"{total_items} матеріалів · {len(all_rows)} країн · {today:%d.%m.%Y}",
            fontsize=10, color=DIM, va="top", ha="right")

    seg = (right - x) / len(rows)
    y = H - 0.95
    for i, (name, _, share) in enumerate(rows):
        sx = x + i * seg
        accent = name in HIGHLIGHT
        color = ACCENT if accent else BAR
        ax.text(sx, y, f"{share:g}%", fontsize=11.5,
                color=ACCENT if accent else MUTED, va="bottom",
                fontweight="bold" if accent else "normal")
        ax.add_patch(Rectangle((sx, y - 0.20), seg * 0.82 * (share / top), 0.11,
                               facecolor=color, edgecolor="none"))
        ax.text(sx, y - 0.30, UA.get(name, name)[:12], fontsize=10.5,
                color=ACCENT if accent else MUTED, va="top")

    out = ROOT / "charts"
    out.mkdir(exist_ok=True)
    path = out / f"{today.isoformat()}.png"
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    print(f"Смужка уваги: {path.name}, країн {len(rows)}")


if __name__ == "__main__":
    main()

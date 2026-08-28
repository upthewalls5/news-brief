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
        from matplotlib.patches import FancyBboxPatch
    except Exception as exc:
        print(f"matplotlib недоступний ({exc}), графік пропускаю")
        return

    rows = all_rows[:TOP]
    total_items = sum(r[1] for r in all_rows)
    top_share = rows[0][2]

    n = len(rows)
    fig_h = 0.40 * n + 1.7
    fig, ax = plt.subplots(figsize=(7.6, fig_h), dpi=200)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Ранжування читається через насиченість: перші рядки темніші.
    for i, (name, count, share) in enumerate(rows):
        y = n - i
        w = share / top_share
        accent = name in HIGHLIGHT
        color = ACCENT if accent else BASE
        alpha = 1.0 if accent else 0.92 - 0.045 * i

        ax.add_patch(FancyBboxPatch(
            (0, y - 0.21), w, 0.42,
            boxstyle="round,pad=0,rounding_size=0.06",
            linewidth=0, facecolor=color, alpha=alpha,
            mutation_aspect=0.18))

        ax.text(-0.02, y, UA.get(name, name), ha="right", va="center",
                fontsize=10.5, color=INK,
                fontweight="semibold" if accent else "normal")
        ax.text(w + 0.015, y, f"{share:g}%", ha="left", va="center",
                fontsize=9.5, color=color if accent else MUTED,
                fontweight="semibold" if accent else "normal")

    today = datetime.now(timezone.utc).date()
    ax.text(-0.34, n + 1.22, "Карта уваги світової преси",
            ha="left", va="bottom", fontsize=14, fontweight="bold", color=INK)
    ax.text(-0.34, n + 0.84,
            f"Частка країни в новинному потоці за добу · {today:%d.%m.%Y}",
            ha="left", va="bottom", fontsize=9.5, color=MUTED)
    ax.text(-0.34, 0.30,
            f"{total_items} матеріалів · {len(all_rows)} країн · "
            f"показано {n} найбільших",
            ha="left", va="top", fontsize=8.5, color=MUTED)

    ax.set_xlim(-0.34, 1.09)
    ax.set_ylim(0.05, n + 1.6)
    ax.axis("off")
    fig.tight_layout(pad=0.6)

    out = ROOT / "charts"
    out.mkdir(exist_ok=True)
    path = out / f"{today.isoformat()}.png"
    fig.savefig(path, bbox_inches="tight", facecolor="white", pad_inches=0.35)
    plt.close(fig)
    print(f"Графік: {path.name}, країн {n}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
collage.py — символьний колаж дня для картки випуску.

Не ілюстрація, а композиція з даних: теми, про які йдеться у випуску,
перетворюються на символи, розмір яких залежить від того, скільки місця
тема зайняла в тексті. Щодня різна, бо різні теми.

Читає:  issues/YYYY-MM-DD.md
Пише:   charts/collage-YYYY-MM-DD.png (прозорий фон, під темну картку)

Символи взяті лише ті, що напевно є у шрифті DejaVu Sans — інакше
на місці гліфа буде порожній прямокутник.
"""

import math
import random
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Тема -> (символ, ключові слова). Слова шукаються в нижньому регістрі,
# тому корені без закінчень: "санкц" зловить і санкції, і санкційний.
THEMES = [
    ("війна",        "⚔", ["війн", "фронт", "наступ", "обстріл", "дрон", "ракет",
                            "удар", "окуп", "оборон", "мобіліз"]),
    ("енергетика",   "⚡", ["енерг", "електро", "генерац", "блекаут", "газ",
                            "нафт", "нпз", "паливн", "тец"]),
    ("санкції",      "⚖", ["санкц", "ембарго", "обмежен", "заборон", "блеклист"]),
    ("торгівля",     "⚓", ["мит", "тариф", "торгов", "експорт", "імпорт",
                            "постачанн", "логістик"]),
    ("гроші",        "♦", ["ринок", "ринк", "інфляц", "ставк", "валют", "курс",
                            "бірж", "інвестиц", "борг", "дефіцит", "бюджет"]),
    ("вибори",       "⚑", ["вибор", "голосуван", "парламент", "коаліц",
                            "відставк", "уряд", "референдум"]),
    ("дипломатія",   "✆", ["перемовин", "переговор", "саміт", "візит",
                            "делегац", "домовлен", "угод"]),
    ("розвідка",     "☾", ["розвідк", "цру", "спецслужб", "шпигун", "витік",
                            "таємн"]),
    ("технології",   "⚙", ["технолог", "штучн інтелект", "ші ", "чип",
                            "напівпровідник", "платформ", "алгоритм"]),
    ("ядерне",       "☢", ["ядерн", "атомн", "реактор", "збагачен", "мааг"]),
    ("авіація",      "✈", ["літак", "авіа", "аеропорт", "борт", "рейс"]),
    ("протести",     "☭", ["протест", "мітинг", "страйк", "демонстрац",
                            "заворушен"]),
    ("суд",          "⚱", ["суд", "трибунал", "позов", "вирок", "розслідуван",
                            "прокурор"]),
    ("катастрофа",   "⚠", ["повін", "землетрус", "пожеж", "катастроф",
                            "загибл", "жертв", "евакуац", "шторм"]),
    ("медицина",     "⚕", ["хворо", "епідем", "вакцин", "лікарн", "спалах"]),
    ("клімат",       "☁", ["клімат", "викид", "потеплін", "посух", "льодовик"]),
    ("релігія",      "☪", ["релігі", "церкв", "мечет", "патріарх", "духовн"]),
    ("медіа",        "✉", ["медіа", "видан", "журналіст", "цензур",
                            "пропаганд", "дезінформ"]),
    ("міграція",     "⌂", ["мігра", "біжен", "кордон", "депорт", "притулок"]),
    ("космос",       "★", ["супутник", "космос", "ракетн запуск", "орбіт"]),
]

ACCENT = "#e2603f"
BASE = "#5f88a8"
PALE = "#33414f"


def detect(text):
    """Вага теми — скільки її ключів трапилось у випуску."""
    low = text.lower()
    found = []
    for name, glyph, keys in THEMES:
        score = sum(low.count(k) for k in keys)
        if score:
            found.append([name, glyph, score])
    found.sort(key=lambda x: x[2], reverse=True)
    return found


def layout(items, seed):
    """Розміщення за спіраллю Фібоначчі: кут 137.5° між сусідами дає
    рівномірне заповнення кола без порожнеч і без перебору варіантів.
    Так само розташовані насінини в соняшнику.

    Найважча тема стоїть у центрі, далі за спаданням ваги назовні."""
    rnd = random.Random(seed)
    n = len(items)
    golden = math.pi * (3 - math.sqrt(5))
    phase = rnd.uniform(0, 2 * math.pi)   # щодня інший поворот композиції

    out = []
    for i, (name, glyph, score, size) in enumerate(items):
        # +0.42 відсуває сусідів від центрального символа,
        # інакше найважча тема перекривається другою за вагою
        r = 0.99 * math.sqrt((i + 0.42) / (n + 0.42))
        ang = i * golden + phase
        x = math.cos(ang) * r
        y = math.sin(ang) * r * 0.95
        jitter = 0.035
        x += rnd.uniform(-jitter, jitter)
        y += rnd.uniform(-jitter, jitter)
        out.append([name, glyph, x, y, size, rnd.uniform(-18, 18)])
    return out


def main():
    today = datetime.now(timezone.utc).date()
    iso = today.isoformat()
    src = ROOT / "issues" / f"{iso}.md"
    if not src.exists():
        print("Немає випуску, колаж не малюю")
        return

    themes = detect(src.read_text(encoding="utf-8"))
    if len(themes) < 4:
        print(f"Тем замало ({len(themes)}), колаж не малюю")
        return

    themes = themes[:16]
    top = themes[0][2]
    items = []
    for i, (name, glyph, score) in enumerate(themes):
        size = 30 + 62 * (score / top) ** 0.55
        items.append((name, glyph, score, size))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"matplotlib недоступний ({exc}), колаж пропускаю")
        return

    # Той самий колаж двічі: маленький для картки в Telegram і великий
    # для сайту, де він працює як головна ілюстрація випуску.
    # Крупніше: на сайті колаж стоїть на всю ширину колонки,
    # а не мініатюрою в кутку картки.
    fig = plt.figure(figsize=(7.2, 7.2), dpi=170)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-1.22, 1.22); ax.set_ylim(-1.22, 1.22)
    ax.axis("off")
    ax.set_facecolor("none")

    # Насінину беремо з дати: та сама дата — та сама композиція,
    # інша дата — інша. Відтворюваність важлива для перезапусків.
    seed = int(iso.replace("-", ""))
    circle = plt.Circle((0, 0), 1.14, fill=False, color=PALE, linewidth=1.1)
    ax.add_patch(circle)

    for i, (name, glyph, x, y, size, rot) in enumerate(layout(items, seed)):
        if i == 0:
            color, alpha = ACCENT, 1.0
        elif i < 4:
            color, alpha = BASE, 0.95
        else:
            color, alpha = BASE, 0.42
        ax.text(x, y, glyph, fontsize=size, color=color, alpha=alpha,
                ha="center", va="center", rotation=rot)

    out = ROOT / "charts"
    out.mkdir(exist_ok=True)
    path = out / f"collage-{iso}.png"
    fig.savefig(path, transparent=True, bbox_inches="tight", pad_inches=0.05)
    big = out / f"collage-big-{iso}.png"
    fig.set_size_inches(9.0, 9.0)
    fig.savefig(big, dpi=170, transparent=True, bbox_inches="tight",
                pad_inches=0.12)
    plt.close(fig)
    print("Колаж: " + path.name + " · теми: "
          + ", ".join(f"{n}({s})" for n, _, s, _ in items[:6]))


if __name__ == "__main__":
    main()

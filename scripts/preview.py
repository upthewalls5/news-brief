#!/usr/bin/env python3
"""
preview.py — картка випуску для стрічки Telegram.

Єдине місце продукту, де ми повністю контролюємо оформлення: Telegraph не
приймає ні CSS, ні шрифтів, а тут усе наше. Тому сюди й винесена вся робота
з формою.

Читає:  issues/YYYY-MM-DD.md, issues/hook-YYYY-MM-DD.txt, digests/latest.md
Пише:   charts/preview-YYYY-MM-DD.png
"""

import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BG = "#12161d"
CARD = "#1a1f28"
INK = "#f2f4f7"
MUTED = "#8b95a5"
DIM = "#5a6472"
ACCENT = "#e2603f"
BAR = "#4d6b82"

MONTHS = ("січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")
HEAD = re.compile(r"^###\s+(.+?)\s+\((\d+)\s+матеріал\w*,\s*([\d.]+)%")
UA = {"Ukraine": "Україна", "USA": "США", "Russia": "росія", "China": "Китай",
      "Germany": "Німеччина", "France": "Франція", "UK": "Британія",
      "Poland": "Польща", "Israel": "Ізраїль", "Iran": "Іран", "India": "Індія",
      "Taiwan": "Тайвань", "Japan": "Японія", "South Korea": "Корея",
      "Italy": "Італія", "Spain": "Іспанія", "Turkey": "Туреччина",
      "Brazil": "Бразилія", "Mexico": "Мексика", "UAE": "ОАЕ",
      "EU-Brussels": "Брюссель", "Global": "Агенції"}


def read_greeting(iso):
    p = ROOT / "issues" / f"greet-{iso}.txt"
    if p.exists():
        g = p.read_text(encoding="utf-8").strip().split("\n")[0][:60]
        if len(g) > 4:
            return g.upper()
    return "РАНКОВИЙ БРІФ"


def read_hooks(iso, limit=2):
    p = ROOT / "issues" / f"hook-{iso}.txt"
    if not p.exists():
        return []
    out = [l.strip().lstrip("-•—→ ").strip()
           for l in p.read_text(encoding="utf-8").splitlines()]
    return [l for l in out if len(l) > 12][:limit]



DAY_TAG = re.compile(r"^(день)\s+(\d+)\s*[:—-]\s*(.)", re.I)


def normalize(line: str) -> str:
    """Позначка дня має виглядати однаково незалежно від того, як її
    написала модель: «День 4 — Текст»."""
    m = DAY_TAG.match(line.strip())
    if m:
        return f"День {m.group(2)} — {m.group(3).upper()}" + line.strip()[m.end():]
    return line

def read_points(iso, limit=3):
    """Перші речення пунктів блоку ГОЛОВНЕ."""
    p = ROOT / "issues" / f"{iso}.md"
    if not p.exists():
        return []
    inside, out = False, []
    for raw in p.read_text(encoding="utf-8").split("\n"):
        line = raw.strip()
        if line and line[0] in "🌍🔀🔗📍💰🗞🕳📡🔮🎯🗓🧭📖":
            if inside:
                break
            inside = line[0] == "🌍"
            continue
        if not inside or not line or line.startswith("Джерела:"):
            continue
        m = re.match(r"^(.+?[.!?…])(\s|$)", line)
        out.append(normalize((m.group(1) if m else line).strip()))
        if len(out) >= limit:
            break
    return out


def read_shares(limit=6):
    d = ROOT / "digests" / "latest.md"
    if not d.exists():
        return [], 0, 0
    rows = []
    for line in d.read_text(encoding="utf-8").split("\n"):
        m = HEAD.match(line.strip())
        if m:
            rows.append((m.group(1), int(m.group(2)), float(m.group(3))))
    rows.sort(key=lambda x: x[1], reverse=True)
    return rows[:limit], sum(r[1] for r in rows), len(rows)


def main():
    today = datetime.now(timezone.utc).date()
    iso = today.isoformat()

    hooks = read_hooks(iso)
    points = []   # тези прибрані: на картці лишаються тільки гачки
    shares, total, n_countries = read_shares()
    if not hooks and not points:
        print("Немає ні гачків, ні тез — картку не малюю")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle
    except Exception as exc:
        print(f"matplotlib недоступний ({exc}), картку пропускаю")
        return

    # Розкладка рахується в дюймах від верху, і вже під неї підбирається
    # висота полотна. Інакше при короткому випуску лишається провал по центру.
    PAD_TOP, PAD_BOTTOM, PAD_X = 0.62, 0.58, 0.72
    H_HEADER, H_RULE = 0.34, 0.30
    H_HOOK, GAP_HOOK = 0.42, 0.12
    H_POINT, GAP_POINT = 0.27, 0.10
    H_STRIP = 1.15
    W = 12.0
    COLLAGE = ROOT / "charts" / f"collage-{iso}.png"
    has_collage = COLLAGE.exists()
    text_right = 8.6 if has_collage else W - 0.72

    wrap_hook = 42 if has_collage else 52
    wrap_point = 58 if has_collage else 74
    hook_lines = [textwrap.wrap(h, wrap_hook) for h in hooks]
    point_lines = [textwrap.wrap(p, wrap_point)[:2] for p in points]

    content = PAD_TOP + H_HEADER + H_RULE
    content += sum(len(w) * H_HOOK + GAP_HOOK for w in hook_lines)
    if point_lines:
        content += 0.12 + sum(len(w) * H_POINT + GAP_POINT for w in point_lines)
    if shares:
        content += H_STRIP
    H = content + PAD_BOTTOM
    if has_collage:
        H = max(H, 4.9)

    fig = plt.figure(figsize=(W, H), dpi=110)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")

    ax.add_patch(Rectangle((0.28, 0.26), W - 0.56, H - 0.52,
                           facecolor=CARD, edgecolor="none", zorder=0))
    ax.add_patch(Rectangle((0.28, 0.26), 0.075, H - 0.52,
                           facecolor=ACCENT, edgecolor="none", zorder=1))

    x = PAD_X
    right = text_right
    y = H - PAD_TOP

    ax.text(x, y, read_greeting(iso), fontsize=13, color=MUTED,
            fontweight="bold", va="top")
    ax.text(W - PAD_X, y,
            f"{today.day} {MONTHS[today.month - 1]} {today.year}", fontsize=13,
            color=DIM, va="top", ha="right")
    y -= H_HEADER
    ax.plot([x, right], [y, y], color="#2b3240", linewidth=1.2)
    y -= H_RULE

    for wrapped in hook_lines:
        for part in wrapped:
            ax.text(x, y, part, fontsize=23, color=INK, fontweight="bold",
                    va="top")
            y -= H_HOOK
        y -= GAP_HOOK

    if point_lines:
        y -= 0.12
        for wrapped in point_lines:
            ax.text(x, y - 0.02, "—", fontsize=13, color=ACCENT, va="top")
            for part in wrapped:
                ax.text(x + 0.26, y, part, fontsize=13.5, color=MUTED, va="top")
                y -= H_POINT
            y -= GAP_POINT

    if has_collage:
        import matplotlib.image as mpimg
        img = mpimg.imread(str(COLLAGE))
        side = min(2.85, H - 2.05)
        cx = (text_right + W - PAD_X) / 2 + 0.25
        cy = H / 2 + 0.18
        ax.imshow(img, extent=(cx - side / 2, cx + side / 2,
                               cy - side / 2, cy + side / 2), zorder=2)
        ax.set_xlim(0, W); ax.set_ylim(0, H)

    if shares:
        y -= 0.34
        ax.text(x, y, "УВАГА ПРЕСИ ЗА ДОБУ", fontsize=9.5, color=DIM,
                fontweight="bold", va="top")
        ax.text(x + 2.15, y, f"{total} матеріалів · {n_countries} країн",
                fontsize=9.5, color=DIM, va="top")
        y -= 0.46

        top = shares[0][2]
        seg = (W - PAD_X - x) / len(shares)
        for i, (name, _, share) in enumerate(shares):
            sx = x + i * seg
            accent = name in ("Ukraine", "Україна")
            color = ACCENT if accent else BAR
            ax.text(sx, y, f"{share:g}%", fontsize=9.5,
                    color=ACCENT if accent else DIM, va="bottom")
            ax.add_patch(Rectangle((sx, y - 0.17), seg * 0.80 * (share / top),
                                   0.10, facecolor=color, edgecolor="none"))
            ax.text(sx, y - 0.24, UA.get(name, name)[:12], fontsize=9.5,
                    color=ACCENT if accent else MUTED, va="top")

    out = ROOT / "charts"
    out.mkdir(exist_ok=True)
    path = out / f"preview-{iso}.png"
    fig.savefig(path, facecolor=BG)
    plt.close(fig)
    print(f"Картка: {path.name}")


if __name__ == "__main__":
    main()

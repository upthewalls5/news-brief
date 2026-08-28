#!/usr/bin/env python3
"""
calendar_img.py — календар майбутніх подій картинкою.

Читає:  state/calendar.md
Пише:   charts/calendar-YYYY-MM-DD.png

Малює три найближчі місяці сіткою. Дні з подіями підсвічені, діапазони
показані суцільною смугою. Під сіткою — перелік із поясненнями.
"""

import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MONTHS_IN = 3

BG = "#12161d"
CARD = "#1a1f28"
INK = "#f2f4f7"
MUTED = "#8b95a5"
DIM = "#5a6472"
ACCENT = "#e2603f"
GRID = "#2b3240"

MONTH_NAME = ("Січень", "Лютий", "Березень", "Квітень", "Травень", "Червень",
              "Липень", "Серпень", "Вересень", "Жовтень", "Листопад", "Грудень")
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд")

LINE = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2})(?:\s*→\s*(\d{4}-\d{2}-\d{2}))?\]\s*(.+)$")


def read_events():
    p = ROOT / "state" / "calendar.md"
    if not p.exists():
        return []
    out = []
    for raw in p.read_text(encoding="utf-8").split("\n"):
        m = LINE.match(raw.strip())
        if not m:
            continue
        try:
            start = date.fromisoformat(m.group(1))
            end = date.fromisoformat(m.group(2)) if m.group(2) else start
        except ValueError:
            continue
        out.append((start, end, m.group(3).strip()))
    out.sort(key=lambda e: e[0])
    return out


def month_matrix(year, month):
    """Тижні місяця, понеділок першим. 0 — порожня клітинка."""
    first = date(year, month, 1)
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    days = (nxt - first).days
    lead = first.weekday()
    cells = [0] * lead + list(range(1, days + 1))
    cells += [0] * (-len(cells) % 7)
    return [cells[i:i + 7] for i in range(0, len(cells), 7)]


def main():
    events = read_events()
    if not events:
        print("Календар порожній, картинку не малюю")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle, Circle
    except Exception as exc:
        print(f"matplotlib недоступний ({exc}), календар пропускаю")
        return

    today = datetime.now(timezone.utc).date()
    marked = {}
    for start, end, body in events:
        d = start
        while d <= end and (d - start).days < 60:
            marked.setdefault(d, []).append(body)
            d += timedelta(days=1)

    months = []
    y, m = today.year, today.month
    for i in range(MONTHS_IN):
        # Два місяці показуємо завжди, третій — тільки якщо в ньому є події.
        # Порожня колонка нічого не додає, а місця з'їдає третину.
        if i < 2 or any(d.year == y and d.month == m for d in marked):
            months.append((y, m))
        y, m = y + (m == 12), (m % 12) + 1

    shown = [e for e in events if e[0] <= date(months[-1][0], months[-1][1], 28)]
    shown = shown[:10]

    COL_W, ROW_H = 3.5, 0.34
    W = 3.9 * len(months) + 0.6
    weeks = max(len(month_matrix(yy, mm)) for yy, mm in months)
    grid_h = 1.05 + 0.62 + weeks * ROW_H      # заголовок + дні тижня + рядки
    list_h = 0.34 * len(shown) + 0.55
    H = grid_h + list_h + 0.55

    fig = plt.figure(figsize=(W, H), dpi=140)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W); ax.set_ylim(0, H); ax.axis("off")
    ax.add_patch(Rectangle((0.25, 0.22), W - 0.5, H - 0.44,
                           facecolor=CARD, edgecolor="none"))
    ax.add_patch(Rectangle((0.25, 0.22), 0.07, H - 0.44,
                           facecolor=ACCENT, edgecolor="none"))

    ax.text(0.62, H - 0.55, "КАЛЕНДАР ПОДІЙ ПОПЕРЕДУ", fontsize=11.5,
            color=MUTED, fontweight="bold", va="top")

    top = H - 1.02
    for i, (yy, mm) in enumerate(months):
        ox = 0.62 + i * COL_W
        ax.text(ox, top, f"{MONTH_NAME[mm - 1]} {yy}", fontsize=10.5,
                color=INK, fontweight="bold", va="top")
        for k, wd in enumerate(WEEKDAYS):
            ax.text(ox + 0.16 + k * 0.42, top - 0.34, wd, fontsize=7.5,
                    color=DIM, ha="center", va="top")
        for r, week in enumerate(month_matrix(yy, mm)):
            for c, day in enumerate(week):
                if not day:
                    continue
                cx = ox + 0.16 + c * 0.42
                cy = top - 0.62 - r * ROW_H
                d = date(yy, mm, day)
                if d in marked:
                    ax.add_patch(Circle((cx, cy + 0.05), 0.145,
                                        facecolor=ACCENT, edgecolor="none"))
                    color, weight = "white", "bold"
                elif d == today:
                    ax.add_patch(Circle((cx, cy + 0.05), 0.145, fill=False,
                                        edgecolor=MUTED, linewidth=1.0))
                    color, weight = INK, "normal"
                elif d < today:
                    color, weight = "#3c4552", "normal"
                else:
                    color, weight = MUTED, "normal"
                ax.text(cx, cy, str(day), fontsize=8, color=color,
                        ha="center", va="center", fontweight=weight)

    ly = list_h - 0.10
    ax.plot([0.62, W - 0.62], [ly + 0.30, ly + 0.30], color=GRID, linewidth=1)
    for start, end, body in shown:
        when = f"{start.day:02d}.{start.month:02d}"
        if end != start:
            when += f"–{end.day:02d}.{end.month:02d}"
        ax.text(0.62, ly, when, fontsize=9, color=ACCENT,
                fontweight="bold", va="top")
        ax.text(1.60, ly, body[:96], fontsize=9, color=MUTED, va="top")
        ly -= 0.34

    out = ROOT / "charts"
    out.mkdir(exist_ok=True)
    path = out / f"calendar-{today.isoformat()}.png"
    fig.savefig(path, facecolor=BG, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)
    print(f"Календар: {path.name}, подій {len(events)}, у списку {len(shown)}")


if __name__ == "__main__":
    main()

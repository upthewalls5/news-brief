#!/usr/bin/env python3
"""
pages.py — повна версія випуску як сторінка на GitHub Pages.

Telegraph тримає близько 20 КБ і не дає керувати оформленням. Тут немає
ні того, ні того обмеження: власна типографіка, своя сітка, різне
оформлення для кожної рубрики за її голосом.

Задум оформлення. Це не блог і не лендинг, а газетна шпальта: вузька
колонка тексту, серифний шрифт для читання, гротеск для службового,
багато повітря. Кольору майже немає — один акцент на всю сторінку,
як червона фарба в друкарні, яку економили.

Кожна рубрика оформлена за своєю природою:
  ГОЛОВНЕ            — великий кегль, лід, як передовиця
  РОЗКОЛ ОПТИКИ      — полюси картками з кольоровим корінцем
  ЩО З ЧОГО ВИПЛИВАЄ — стрічка з вузлами, як хронологія
  ПУЛЬС КРАЇН        — щільна сітка, назва країни капітеллю
  ГРОШІ              — табличні цифри моноширинним
  МАСОВА ОПТИКА      — курсив, приглушений колір
  СЛІПА ЗОНА         — темний блок, інверсія
  РАДАР              — значки впевненості
  ПРОГНОЗИ           — картки зі шкалою
  ЩО ПОПЕРЕДУ        — календарний список

Читає:  issues/YYYY-MM-DD.md, charts/*.png
Пише:   docs/YYYY-MM-DD.html, docs/index.html, docs/archive.html
"""

import html
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

RUBRIC_EMOJI = "🌍🔀🔗📍💰🗞🕳📡🔮🗓🧭📖🎯"
FLAG = re.compile(r"^([\U0001F1E6-\U0001F1FF]{2}|[^\w\s])\s*([^:]{2,48}):\s*(.*)$")
NAMED = re.compile(r"^([A-ZА-ЯЄІЇҐ][^:]{1,32}):\s+(.+)$")
CONF = re.compile(r"^\[(висока|середня|низька)\s+впевненість\]\s*(.+)$", re.I)
URL = re.compile(r"(https?://\S+)")
MONTHS = ("січня", "лютого", "березня", "квітня", "травня", "червня",
          "липня", "серпня", "вересня", "жовтня", "листопада", "грудня")

SLUG = {"ГОЛОВНЕ": "lead", "РОЗКОЛ ОПТИКИ": "split", "ЩО З ЧОГО ВИПЛИВАЄ": "chain",
        "ПУЛЬС КРАЇН": "pulse", "ГРОШІ": "money", "МАСОВА ОПТИКА": "mass",
        "УКРАЇНСЬКИЙ ВИМІР": "ua", "СЛІПА ЗОНА": "blind", "РАДАР": "radar",
        "ПРОГНОЗИ": "forecast", "ЩО ПОПЕРЕДУ": "ahead"}

CSS = """
:root{
  --ink:#14161a; --muted:#6b7280; --faint:#9aa3af; --line:#e3e2de;
  --paper:#faf9f6; --card:#ffffff; --accent:#c0442f; --deep:#1b2430;
  --serif:'Literata',Georgia,'Times New Roman',serif;
  --sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  --mono:'JetBrains Mono',ui-monospace,'SF Mono',Menlo,monospace;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);
  font-family:var(--serif);font-size:19px;line-height:1.62;
  font-feature-settings:"kern","liga";text-rendering:optimizeLegibility}
.wrap{max-width:720px;margin:0 auto;padding:0 22px 96px}

/* ── шапка ─────────────────────────────────────────────── */
.masthead{border-bottom:2px solid var(--ink);margin:0 0 34px;padding:38px 0 14px}
.masthead .kicker{font-family:var(--sans);font-size:11px;letter-spacing:.22em;
  text-transform:uppercase;color:var(--muted);margin:0 0 10px}
.masthead h1{font-family:var(--serif);font-weight:700;font-size:38px;
  line-height:1.16;margin:0 0 12px;letter-spacing:-.015em}
.masthead .meta{display:flex;justify-content:space-between;align-items:baseline;
  gap:14px;font-family:var(--sans);font-size:12.5px;color:var(--muted);
  border-top:1px solid var(--line);padding-top:11px;flex-wrap:wrap}
.masthead .meta b{color:var(--ink);font-weight:600}

/* ── рубрики ───────────────────────────────────────────── */
section{margin:0 0 52px;scroll-margin-top:20px}
section>h2{font-family:var(--sans);font-size:12px;font-weight:700;
  letter-spacing:.2em;text-transform:uppercase;color:var(--accent);
  margin:0 0 20px;padding-bottom:9px;border-bottom:1px solid var(--line);
  display:flex;align-items:center;gap:9px}
section>h2 .ic{font-size:15px;filter:grayscale(1) opacity(.75)}
p{margin:0 0 17px}

/* ГОЛОВНЕ — передовиця */
#lead p{font-size:20.5px;line-height:1.58}
#lead p:first-of-type{font-size:23px;line-height:1.48}
#lead p:first-of-type::first-letter{float:left;font-size:62px;line-height:.82;
  padding:5px 11px 0 0;font-weight:700;color:var(--accent)}
#lead .dur{font-family:var(--sans);font-size:12px;color:var(--faint)}

/* РОЗКОЛ ОПТИКИ — полюси */
.pole{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--deep);
  padding:13px 17px;margin:0 0 9px;font-size:17.5px;line-height:1.55}
.pole b{font-family:var(--sans);font-size:14px;letter-spacing:.01em}
.pole .fl{margin-right:7px}
.note{font-family:var(--sans);font-size:15px;color:var(--muted);
  margin:13px 0 8px;padding-left:14px;border-left:2px solid var(--accent)}
.note b{color:var(--ink);font-weight:600}
.evt{font-family:var(--sans);font-weight:600;font-size:16px;margin:26px 0 12px;
  color:var(--deep)}
.evt::before{content:"";display:inline-block;width:16px;height:1px;
  background:var(--accent);vertical-align:middle;margin-right:9px}

/* ЩО З ЧОГО ВИПЛИВАЄ — стрічка */
.chain{border-left:2px solid var(--line);margin:0 0 26px;padding:2px 0 2px 22px;
  position:relative}
.chain h3{font-family:var(--sans);font-size:15.5px;font-weight:600;margin:0 0 9px}
.chain h3::before{content:"";position:absolute;left:-5px;top:8px;width:8px;height:8px;
  border-radius:50%;background:var(--accent)}
.chain p{font-size:17px;color:#2c3138;margin:0}
.chain .ar{color:var(--accent);font-weight:600;padding:0 3px}
.chain .dt{font-family:var(--mono);font-size:13.5px;color:var(--muted);
  background:#f1efe9;padding:1px 6px;border-radius:3px}

/* ПУЛЬС КРАЇН — сітка */
.grid{display:grid;grid-template-columns:1fr 1fr;gap:0 26px}
.row{border-top:1px solid var(--line);padding:10px 0;font-size:16.5px;line-height:1.5}
.row:first-child,.grid .row:nth-child(2){border-top:0}
.row .cn{display:block;font-family:var(--sans);font-size:11.5px;font-weight:700;
  letter-spacing:.13em;text-transform:uppercase;color:var(--accent);margin-bottom:2px}

/* ГРОШІ */
#money p{font-size:17px}
#money .num{font-family:var(--mono);font-size:16px;font-variant-numeric:tabular-nums}

/* МАСОВА ОПТИКА */
#mass p{font-style:italic;color:#4b5159;font-size:17.5px}

/* СЛІПА ЗОНА — інверсія */
#blind{background:var(--deep);color:#e8eaed;padding:26px 24px 10px;
  margin-left:-24px;margin-right:-24px}
#blind>h2{color:#e2603f;border-bottom-color:rgba(255,255,255,.14)}
#blind p{color:#c9cdd3;font-size:17.5px}

/* РАДАР */
.sig{display:flex;gap:13px;align-items:flex-start;border-top:1px solid var(--line);
  padding:14px 0}
.badge{flex:0 0 auto;font-family:var(--sans);font-size:10.5px;font-weight:700;
  letter-spacing:.1em;text-transform:uppercase;padding:3px 8px;border-radius:2px;
  margin-top:3px;white-space:nowrap}
.b-high{background:var(--accent);color:#fff}
.b-mid{background:#e5e2da;color:#4b5159}
.b-low{background:transparent;color:var(--faint);border:1px solid var(--line)}
.sig p{margin:0;font-size:16.5px}

/* ПРОГНОЗИ */
.fc{background:var(--card);border:1px solid var(--line);padding:15px 17px;
  margin:0 0 10px}
.fc p{margin:0 0 11px;font-size:17px}
.bar{height:4px;background:#eceae4;position:relative;border-radius:2px;overflow:hidden}
.bar i{position:absolute;inset:0 auto 0 0;background:var(--accent);border-radius:2px}
.bar .base{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--deep)}
.fcmeta{display:flex;justify-content:space-between;font-family:var(--sans);
  font-size:11.5px;color:var(--muted);margin-top:6px}

/* ЩО ПОПЕРЕДУ */
.ah{display:flex;gap:15px;border-top:1px solid var(--line);padding:11px 0;
  font-size:16.5px}
.ah .d{flex:0 0 92px;font-family:var(--mono);font-size:13.5px;color:var(--accent);
  padding-top:3px}

figure{margin:0 0 30px}
figure img{width:100%;display:block;border:1px solid var(--line)}
figcaption{font-family:var(--sans);font-size:12px;color:var(--faint);
  margin-top:8px;text-align:center}
a{color:var(--accent);text-decoration:none;border-bottom:1px solid rgba(192,68,47,.3)}
a:hover{border-bottom-color:var(--accent)}
footer{border-top:1px solid var(--line);margin-top:56px;padding-top:20px;
  font-family:var(--sans);font-size:12.5px;color:var(--faint);line-height:1.65}
.arch{font-family:var(--sans);font-size:14px}
.arch a{display:block;padding:11px 0;border-bottom:1px solid var(--line);
  border-bottom-color:var(--line);color:var(--ink)}
.arch a span{color:var(--muted);font-size:12.5px;margin-left:9px}

/* поява під час гортання — стримано, без атракціону */
.rv{opacity:0;transform:translateY(9px)}
.rv.on{opacity:1;transform:none;transition:opacity .5s ease,transform .5s ease}
@media (prefers-reduced-motion:reduce){.rv{opacity:1;transform:none}}

@media(max-width:640px){
  body{font-size:18px}
  .wrap{padding:0 17px 70px}
  .masthead h1{font-size:29px}
  #lead p:first-of-type{font-size:20px}
  #lead p:first-of-type::first-letter{font-size:50px}
  .grid{grid-template-columns:1fr}
  .grid .row:nth-child(2){border-top:1px solid var(--line)}
  #blind{margin-left:-17px;margin-right:-17px;padding:22px 17px 6px}
  .ah{flex-direction:column;gap:3px}
  .ah .d{flex:none}
}
@media print{
  body{background:#fff;font-size:11pt}
  .rv{opacity:1;transform:none}
  #blind{background:#fff;color:#000;margin:0;padding:0}
  #blind p,#blind>h2{color:#000}
}
"""

JS = """
const io=new IntersectionObserver((es)=>{es.forEach(e=>{
  if(e.isIntersecting){e.target.classList.add('on');io.unobserve(e.target)}})},
  {rootMargin:'0px 0px -8% 0px'});
document.querySelectorAll('.rv').forEach(el=>io.observe(el));
"""


def esc(t):
    return html.escape(t, quote=False)


def linkify(t):
    return URL.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', esc(t))


def parse(brief):
    """Ділить випуск на рубрики: [(емодзі, назва, [рядки])]."""
    out, cur = [], None
    for raw in brief.split("\n"):
        line = raw.strip()
        if line and line[0] in RUBRIC_EMOJI and line[1:].strip().isupper() \
                and len(line) < 46:
            cur = (line[0], line[1:].strip(), [])
            out.append(cur)
            continue
        if cur and line and not line.startswith("Джерела:"):
            cur[2].append(line)
    return out


def render_lead(lines):
    html_ = []
    for l in lines:
        m = re.search(r"\(([^()]{6,70})\)\s*$", l)
        if m:
            body, dur = l[:m.start()].strip(), m.group(1)
            html_.append(f'<p>{linkify(body)} '
                         f'<span class="dur">{esc(dur)}</span></p>')
        else:
            html_.append(f"<p>{linkify(l)}</p>")
    return "".join(html_)


def render_split(lines):
    out = []
    for l in lines:
        low = l.lower()
        if low.startswith(("замовчують:", "чому розходяться:")):
            lab, _, rest = l.partition(":")
            out.append(f'<p class="note"><b>{esc(lab)}:</b> {linkify(rest.strip())}</p>')
            continue
        m = FLAG.match(l)
        if m:
            fl, name, rest = m.groups()
            out.append(f'<div class="pole"><span class="fl">{esc(fl)}</span>'
                       f'<b>{esc(name.strip())}:</b> {linkify(rest)}</div>')
            continue
        out.append(f'<p class="evt">{linkify(l)}</p>')
    return "".join(out)


def render_chain(lines):
    out, open_ = [], False
    for l in lines:
        is_body = "→" in l or l.startswith("[")
        if not is_body:
            if open_:
                out.append("</div>")
            out.append(f'<div class="chain"><h3>{esc(l)}</h3>')
            open_ = True
            continue
        body = esc(l)
        body = re.sub(r"\[([^\]]{2,28})\]", r'<span class="dt">\1</span>', body)
        body = body.replace("→", '<span class="ar">→</span>')
        if not open_:
            out.append('<div class="chain">')
            open_ = True
        out.append(f"<p>{body}</p>")
    if open_:
        out.append("</div>")
    return "".join(out)


def render_pulse(lines):
    cells = []
    for l in lines:
        m = NAMED.match(l) or FLAG.match(l)
        if m and len(m.groups()) == 2:
            name, rest = m.groups()
        elif m:
            _, name, rest = m.groups()
        else:
            name, rest = "", l
        cells.append(f'<div class="row"><span class="cn">{esc(name.strip())}</span>'
                     f'{linkify(rest)}</div>')
    return '<div class="grid">' + "".join(cells) + "</div>"


def render_radar(lines):
    out = []
    for l in lines:
        m = CONF.match(l)
        if m:
            lvl, rest = m.group(1).lower(), m.group(2)
            cls = {"висока": "b-high", "середня": "b-mid"}.get(lvl, "b-low")
            out.append(f'<div class="sig"><span class="badge {cls}">{esc(lvl)}</span>'
                       f"<p>{linkify(rest)}</p></div>")
        else:
            out.append(f"<p>{linkify(l)}</p>")
    return "".join(out)


def render_forecast(lines):
    out = []
    for l in lines:
        conf = re.search(r"впевненість\s*[—-]?\s*(\d{1,3})\s*%", l, re.I)
        base = re.search(r"базово:?\s*(\d{1,3})\s*%", l, re.I)
        if conf:
            c = int(conf.group(1))
            b = int(base.group(1)) if base else None
            body = re.sub(r"\s*\(базово:?[^)]*\)", "", l)
            body = re.sub(r"\s*[—-]?\s*впевненість\s*[—-]?\s*\d{1,3}\s*%\.?", "", body)
            mark = (f'<span class="base" style="left:{min(b,100)}%"></span>'
                    if b is not None else "")
            out.append(
                f'<div class="fc"><p>{linkify(body.strip(" .—-"))}</p>'
                f'<div class="bar"><i style="width:{min(c,100)}%"></i>{mark}</div>'
                f'<div class="fcmeta"><span>впевненість {c}%</span>'
                f'<span>{f"базово {b}%" if b is not None else ""}</span></div></div>')
        else:
            out.append(f"<p>{linkify(l)}</p>")
    return "".join(out)


def render_ahead(lines):
    out = []
    for l in lines:
        m = re.match(r"^(\d{1,2}\s+\w+|\d{2}\.\d{2}(?:\.\d{4})?)\s*[—–-]\s*(.+)$", l)
        if m:
            out.append(f'<div class="ah"><span class="d">{esc(m.group(1))}</span>'
                       f"<span>{linkify(m.group(2))}</span></div>")
        else:
            out.append(f"<p>{linkify(l)}</p>")
    return "".join(out)


def render_plain(lines):
    return "".join(f"<p>{linkify(l)}</p>" for l in lines)


RENDER = {"lead": render_lead, "split": render_split, "chain": render_chain,
          "pulse": render_pulse, "radar": render_radar,
          "forecast": render_forecast, "ahead": render_ahead}


def page(iso, brief, greeting, stats, images):
    d = datetime.fromisoformat(iso).date()
    date_h = f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    parts = []
    for i, (emoji, name, lines) in enumerate(parse(brief)):
        slug = SLUG.get(name, f"s{i}")
        body = RENDER.get(slug, render_plain)(lines)
        parts.append(
            f'<section id="{slug}" class="rv"><h2><span class="ic">{emoji}</span>'
            f"{esc(name)}</h2>{body}</section>")

    figs = "".join(
        f'<figure class="rv"><img src="{src}" alt="{esc(cap)}" loading="lazy">'
        f"<figcaption>{esc(cap)}</figcaption></figure>" for src, cap in images)

    return f"""<!doctype html>
<html lang="uk"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(greeting)} · {date_h}</title>
<meta name="description" content="Огляд світової преси за {date_h}. {esc(stats)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Literata:ital,wght@0,400;0,600;0,700;1,400&family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;500&display=swap&subset=cyrillic,latin" rel="stylesheet">
<style>{CSS}</style>
</head><body>
<div class="wrap">
<header class="masthead">
  <p class="kicker">Ранковий бріф · огляд світової преси</p>
  <h1>{esc(greeting)}</h1>
  <div class="meta"><span>{date_h}</span><span>{esc(stats)}</span></div>
</header>
{figs}
{"".join(parts)}
<footer>
  Автоматичний огляд світової преси. Порівнюються видання з протилежними
  редакційними позиціями; матеріали державних медіа подаються як офіційна
  позиція, а не як факт.<br>
  <a href="archive.html">Архів випусків</a>
</footer>
</div>
<script>{JS}</script>
</body></html>"""


def archive_page(items):
    rows = "".join(
        f'<a href="{slug}.html">{esc(title)}<span>{iso}</span></a>'
        for slug, iso, title in items)
    return f"""<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Архів випусків</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Literata:wght@400;700&family=Inter:wght@400;600;700&display=swap&subset=cyrillic,latin" rel="stylesheet">
<style>{CSS}</style></head><body><div class="wrap">
<header class="masthead"><p class="kicker">Ранковий бріф</p>
<h1>Архів випусків</h1>
<div class="meta"><span>{len(items)} випусків</span><span><a href="index.html">До останнього</a></span></div>
</header>
<div class="arch">{rows}</div>
</div></body></html>"""


def slug_for(iso):
    """Випадкова адреса випуску. Дата в імені файлу дозволяла б перебрати
    весь архів, підставляючи числа. Відповідність дата-адреса зберігаємо
    окремо, щоб архів і повторні запуски знаходили ту саму сторінку."""
    p = ROOT / "state" / "pages.json"
    m = {}
    if p.exists():
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            m = {}
    if iso not in m:
        m[iso] = secrets.token_hex(5)
        p.parent.mkdir(exist_ok=True)
        p.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return m[iso]


def base_url():
    """Адреса сайту. Cloudflare Pages, якщо налаштований, інакше GitHub Pages."""
    custom = os.environ.get("PAGES_BASE", "").strip().rstrip("/")
    if custom:
        return custom
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if repo and "/" in repo:
        user, name = repo.split("/", 1)
        return f"https://{user}.github.io/{name}"
    return ""


def read(path, default=""):
    p = ROOT / path
    return p.read_text(encoding="utf-8").strip() if p.exists() else default


def main():
    iso = datetime.now(timezone.utc).date().isoformat()
    brief = read(f"issues/{iso}.md")
    if not brief:
        print("Немає випуску за сьогодні, сайт не оновлюю")
        return

    greeting = read(f"issues/greet-{iso}.txt").split("\n")[0] or "Ранковий бріф"

    stats = ""
    digest = read("digests/latest.md")[:400]
    m = re.search(r"Зібрано (\d+) матеріалів", digest)
    n = re.search(r"\((\d+) стрічок", digest)
    if m:
        stats = f"{m.group(1)} матеріалів"
        if n:
            stats += f" · {n.group(1)} джерел"

    images = []
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    for name, cap in ((f"cover-{iso}.png", "Обкладинка випуску"),
                      (f"chart-{iso}.png", "Карта уваги світової преси")):
        if (ROOT / "charts" / name).exists():
            images.append((f"../charts/{name}", cap))
    if (ROOT / "charts" / f"{iso}.png").exists():
        images.append((f"../charts/{iso}.png", "Карта уваги світової преси"))

    DOCS.mkdir(exist_ok=True)
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")
    slug = slug_for(iso)
    doc = page(iso, brief, greeting, stats, images)
    (DOCS / f"{slug}.html").write_text(doc, encoding="utf-8")
    (DOCS / "index.html").write_text(doc, encoding="utf-8")

    mapping = json.loads((ROOT / "state" / "pages.json").read_text(encoding="utf-8"))
    items = []
    for day in sorted(mapping, reverse=True)[:120]:
        if not (DOCS / f"{mapping[day]}.html").exists():
            continue
        g = read(f"issues/greet-{day}.txt").split("\n")[0] or "Випуск"
        items.append((mapping[day], day, g))
    (DOCS / "archive.html").write_text(archive_page(items), encoding="utf-8")

    url = base_url()
    print(f"Сайт: docs/{slug}.html ({len(doc) // 1024} КБ), "
          f"в архіві {len(items)} випусків")
    if url:
        print(f"  адреса: {url}/{slug}.html")


if __name__ == "__main__":
    main()

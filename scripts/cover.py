#!/usr/bin/env python3
"""
cover.py — обкладинка випуску через Gemini (Nano Banana).

Модель отримує САМ ТЕКСТ випуску й вирішує, що зобразити. Раніше тут був
словник мотивів — моя інтерпретація тем, — але вона щодня накладала на
різні дні ту саму сітку образів. Тепер образ народжується з конкретного
випуску, а не з мого припущення про те, як виглядає «війна» чи «вибори».

Два обмеження лишаються, і вони не про стиль. Упізнавані реальні люди —
бо модель або зробить невпізнаваного персонажа, або спотворену подобу
конкретної особи. Фотореалізм новинного кадру — бо таке зображення
сприймається як свідчення, а не як ілюстрація.

Кожен виклик до API незалежний і не має історії, тому обкладинки не
переймають стилістику одна в одної — на відміну від генерації в чаті,
де накопичений контекст затягує всі зображення в один вигляд.

Читає:  issues/keys-YYYY-MM-DD.txt
Пише:   charts/cover-YYYY-MM-DD.png
Провайдери за пріоритетом: Cloudflare Workers AI (безкоштовно, близько
230 зображень на добу), Pollinations (без ключа взагалі), Gemini (платний).
Секрети: CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID, за бажанням GEMINI_API_KEY
"""

import base64
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 150.0

# Три провайдери підряд: перший, що відповість, і малює.
# Cloudflare — основний: FLUX Schnell коштує близько 43 «нейронів» за
# зображення, тобто в добовий безкоштовний бюджет вміщується понад двісті
# картинок. Нам потрібна одна.
# Pollinations — запасний: не потребує ані ключа, ані реєстрації, але
# анонімні зображення можуть мати водяний знак.
# Gemini — останній: платний, вмикається тільки якщо є ключ і перші два
# не спрацювали.
CF_API = "https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{model}"
CF_MODEL = os.environ.get("CLOUDFLARE_IMAGE_MODEL",
                          "@cf/black-forest-labs/flux-1-schnell")
POLLI = "https://image.pollinations.ai/prompt/"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")

# 4:3 — класична газетна пропорція. Не банер, не квадрат: під таким
# співвідношенням ілюстрація над текстом читається на будь-якому екрані,
# і сторінка щодня виглядає однаково зверстаною.
# Підтримувані API значення: 1:1, 3:4, 4:3, 9:16, 16:9.
ASPECT = os.environ.get("GEMINI_ASPECT", "4:3")
IMAGE_SIZE = os.environ.get("GEMINI_IMAGE_SIZE", "2K")

def read_keys(iso):
    """Ключові вирази дня. Їх складає той, хто писав випуск: він щойно
    прочитав дві з половиною тисячі матеріалів і знає, чим був день.
    Художник бачить лише ці вирази, без самих новин."""
    p = ROOT / "issues" / f"keys-{iso}.txt"
    if not p.exists():
        return []
    lines = [l.strip().lstrip("-•—* ").strip()
             for l in p.read_text(encoding="utf-8").splitlines()]
    return [l for l in lines if 6 < len(l) < 90][:8]


def scene_from_keys(keys):
    """Проміжний крок: перетворює образи дня на опис сцени.

    FLUX добре малює за конкретним описом і погано — за переліком
    абстракцій. Тому між образами й художником стоїть модель, яка
    знаходить одну сцену, де ці образи сходяться, і описує її
    англійською: предмети, матеріали, світло, палітра.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    system = ROOT / "prompts" / "scene.md"
    if not key or not system.exists():
        return ""
    try:
        from write import call_api
        out = call_api(key, system.read_text(encoding="utf-8"),
                       "ОБРАЗИ ДНЯ:\n" + "\n".join(f"— {k}" for k in keys),
                       1200)
    except Exception as exc:
        print(f"  опис сцени не склався ({type(exc).__name__})")
        return ""
    out = (out or "").strip().strip('"')
    if len(out) < 60 or len(out) > 1200:
        print(f"  опис сцени підозрілий ({len(out)} символів), беру образи як є")
        return ""
    return out


def build_prompt(keys, scene=""):
    if scene:
        return (
            f"{scene}\n\n"
            "Editorial cover illustration for a serious newspaper: painterly, "
            "restrained, atmospheric, one clear focal point, generous empty "
            "space, visible texture.\n"
            f"Format: {ASPECT} landscape, filled edge to edge, no borders, "
            "no frame, no margins.\n"
            "AVOID: people, faces or silhouettes; any text, letters, numbers, "
            "logos or flags; photorealism or anything resembling a news "
            "photograph; gore; stock-illustration cliches, glossy 3D render, "
            "neon, HDR."
        )

    joined = "\n".join(f"— {k}" for k in keys)
    return (
        "You are illustrating the cover of today's world-news briefing.\n"
        "You will not see the news itself. Instead, here is what the day was "
        "ABOUT, written as a handful of ideas by the editor who read it all:\n\n"
        f"{joined}\n\n"
        "Make one image. Choose the subject, the composition, the format and "
        "the palette yourself, based on these ideas — a scene, an object, a "
        "landscape, an abstraction, whatever holds them together best. "
        "Do not illustrate the ideas one by one: find the single image where "
        "they meet. It should feel like the artwork above a long-form "
        "essay in a serious newspaper — considered, restrained, with real "
        "atmosphere and a clear focal point.\n\n"
        f"Format: {ASPECT} landscape, filled edge to edge, no borders, "
        "no frame, no margins around the artwork.\n\n"
        "AVOID: recognisable real people or faces; any text, letters, numbers, "
        "logos or national flags; photorealism or anything resembling a news "
        "photograph of an actual event; gore or graphic suffering; "
        "stock-illustration cliches, glossy 3D render, neon, HDR."
    )


def from_cloudflare(prompt):
    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    acc = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not (token and acc):
        return None, "немає секретів"
    url = CF_API.format(acc=acc, model=CF_MODEL)
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(url, headers={"Authorization": f"Bearer {token}"},
                            json={"prompt": prompt[:2000], "steps": 6})
    except Exception as exc:
        return None, type(exc).__name__
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code} {r.text[:120]}"
    # FLUX повертає base64 у полі result.image, решта моделей — сирі байти
    ctype = r.headers.get("content-type", "")
    if "json" in ctype:
        img = (r.json().get("result") or {}).get("image")
        if not img:
            return None, "у відповіді немає зображення"
        return base64.b64decode(img), None
    return r.content, None


def from_pollinations(prompt):
    """Без ключа й реєстрації. Анонімні зображення можуть мати водяний знак."""
    url = POLLI + quote(prompt[:1500], safe="")
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            r = client.get(url, params={"width": 1280, "height": 960,
                                        "model": "flux", "nologo": "true",
                                        "seed": datetime.now(timezone.utc).strftime("%Y%m%d")})
    except Exception as exc:
        return None, type(exc).__name__
    if r.status_code >= 400 or len(r.content) < 5000:
        return None, f"HTTP {r.status_code}, {len(r.content)} байт"
    return r.content, None


def from_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None, "немає ключа"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"imageConfig": {"aspectRatio": ASPECT,
                                                 "imageSize": IMAGE_SIZE}}}
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(f"{GEMINI_API}/{GEMINI_MODEL}:generateContent",
                            headers={"x-goog-api-key": key,
                                     "Content-Type": "application/json"},
                            json=body)
    except Exception as exc:
        return None, type(exc).__name__
    if r.status_code >= 400:
        return None, f"HTTP {r.status_code} {r.text[:120]}"
    for cand in r.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"]), None
    return None, "зображення не повернулось"


def main():
    iso = datetime.now(timezone.utc).date().isoformat()
    keys = read_keys(iso)
    if not keys:
        print("Немає образів дня (keys-*.txt) — обкладинку пропускаю")
        return

    print("Образи дня: " + " · ".join(keys[:4]))
    scene = scene_from_keys(keys)
    if scene:
        print(f"Сцена: {scene[:110]}…")
    prompt = build_prompt(keys, scene)

    for name, fn in (("Cloudflare", from_cloudflare),
                     ("Pollinations", from_pollinations),
                     ("Gemini", from_gemini)):
        blob, err = fn(prompt)
        if blob:
            out = ROOT / "charts"
            out.mkdir(exist_ok=True)
            path = out / f"cover-{iso}.png"
            path.write_bytes(blob)
            print(f"Обкладинка від {name}: {path.name}, "
                  f"{path.stat().st_size // 1024} КБ")
            return
        print(f"  {name}: {err}")

    print("Жоден провайдер не дав зображення — обкладинки не буде")


if __name__ == "__main__":
    main()

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
Потрібен секрет: GEMINI_API_KEY
"""

import base64
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
API = "https://generativelanguage.googleapis.com/v1beta/models"
MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
TIMEOUT = 120.0

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


def build_prompt(keys):
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


def main():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        print("Немає секрету GEMINI_API_KEY — обкладинку пропускаю")
        return

    iso = datetime.now(timezone.utc).date().isoformat()

    keys = read_keys(iso)
    if not keys:
        print("Немає образів дня (keys-*.txt) — обкладинку пропускаю")
        return
    prompt = build_prompt(keys)
    print("Образи дня: " + " · ".join(keys[:4]))
    print(f"Модель: {MODEL} | пропорція {ASPECT} | розмір {IMAGE_SIZE}")

    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            r = client.post(f"{API}/{MODEL}:generateContent",
                            headers={"x-goog-api-key": key,
                                     "Content-Type": "application/json"},
                            json={
                                "contents": [{"parts": [{"text": prompt}]}],
                                "generationConfig": {
                                    "imageConfig": {
                                        "aspectRatio": ASPECT,
                                        "imageSize": IMAGE_SIZE,
                                    }
                                },
                            })
    except Exception as exc:
        print(f"Gemini недоступний ({type(exc).__name__}), обкладинки не буде")
        return

    if r.status_code >= 400:
        print(f"Gemini відмовив: {r.status_code} {r.text[:220]}")
        # Старіші моделі не знають imageConfig — пробуємо без нього,
        # хай краще буде картинка іншої пропорції, ніж жодної.
        if "imageConfig" in r.text or "Unknown name" in r.text:
            print("Повторюю без imageConfig")
            try:
                with httpx.Client(timeout=TIMEOUT) as client:
                    r = client.post(f"{API}/{MODEL}:generateContent",
                                    headers={"x-goog-api-key": key,
                                             "Content-Type": "application/json"},
                                    json={"contents": [{"parts": [{"text": prompt}]}]})
            except Exception:
                return
            if r.status_code >= 400:
                return
        else:
            return

    data = r.json()
    blob = None
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                blob = inline["data"]
                break
        if blob:
            break

    if not blob:
        reason = data.get("candidates", [{}])[0].get("finishReason", "?")
        print(f"Зображення не повернулось (finishReason={reason})")
        return

    out = ROOT / "charts"
    out.mkdir(exist_ok=True)
    path = out / f"cover-{iso}.png"
    path.write_bytes(base64.b64decode(blob))
    print(f"Обкладинка: {path.name}, {path.stat().st_size // 1024} КБ")


if __name__ == "__main__":
    main()

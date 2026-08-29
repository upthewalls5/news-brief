#!/usr/bin/env python3
"""
semantics.py — крос-мовна кластеризація за сенсом і числовий індекс розходження.

Чому ембединги, а не переклад плюс ключові слова: багатомовна модель
відображає речення у вектор так, що «Trump imposes tariffs», «Трамп
запровадив мита» і японський заголовок про те саме опиняються поряд без
жодного перекладу. Синонімічні ряди враховані за побудовою.

Окремо про антоніми. Ембединги ставлять протилежні твердження БЛИЗЬКО:
«перемир'я узгоджено» й «перемир'я зірвано» різняться одним словом. Для
пошуку фактів це вада, для нас — те, що треба: кластер, у якому зійшлися
протилежні формулювання про одну подію, і є розколом оптики. Тому спершу
ембединги зводять описи докупи, а вже потім індекс міряє розходження.

Модель: статичні ембединги model2vec (~30 МБ, без torch). Якщо недоступна,
викликач має відкотитись на кластеризацію за словами.
"""

import math
import re
from collections import Counter, defaultdict

MODEL_NAME = "minishlab/M2V_multilingual_output"

# Полюси, які представляють офіційну позицію держави. Розходження між ними
# і незалежними джерелами — найінформативніший вид розколу.
STATE_POLES = {"state", "party-organ", "hardline", "pro-government",
               "state-agency", "state-aligned", "state-adjacent",
               "nationalist", "saudi-aligned", "qatar-aligned"}


def load_model():
    """Повертає модель або None. Помилка тут не має валити збір."""
    try:
        from model2vec import StaticModel
        return StaticModel.from_pretrained(MODEL_NAME)
    except Exception as exc:
        print(f"Ембединги недоступні ({type(exc).__name__}: {exc}), "
              "кластеризую за словами")
        return None


def embed(model, texts):
    import numpy as np
    vecs = model.encode(texts)
    vecs = np.asarray(vecs, dtype="float32")
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def cluster_by_meaning(items, model, threshold=0.62, min_sources=2):
    """Жадібна кластеризація за косинусною близькістю до центроїда.
    Один прохід: список уже відсортований за часом, тож перші матеріали
    сюжету природно стають центрами."""
    import numpy as np

    if not items:
        return []
    vecs = embed(model, [f"{i['title']}. {i.get('lead', '')[:120]}" for i in items])

    centroids = []          # накопичені суми векторів
    members = []            # індекси матеріалів
    for idx in range(len(items)):
        v = vecs[idx]
        best, best_sim = -1, 0.0
        for c, cent in enumerate(centroids):
            norm = np.linalg.norm(cent)
            sim = float(v @ (cent / norm)) if norm else 0.0
            if sim > best_sim:
                best, best_sim = c, sim
        if best >= 0 and best_sim >= threshold:
            centroids[best] += v
            members[best].append(idx)
        else:
            centroids.append(v.copy())
            members.append([idx])

    out = []
    for c, idxs in enumerate(members):
        group = [items[i] for i in idxs]
        sources = {g["source"] for g in group}
        if len(sources) < min_sources:
            continue
        countries = sorted({g["country"] for g in group})
        out.append({
            "items": group,
            "countries": countries,
            "n_sources": len(sources),
            "vecs": vecs[idxs],
            "key": group[0]["title"][:70],
        })
    out.sort(key=lambda c: (len(c["countries"]), c["n_sources"]), reverse=True)
    return out


def _tokens(text):
    return {w for w in re.findall(r"[^\W\d_]{4,}", text.lower())}


def divergence(cluster):
    """Наскільки по-різному подають одну подію. 0-100.

    Три складові:
      • семантична — розкид векторів усередині кластера;
      • полюсна — чи є в кластері і державні, і незалежні джерела;
      • лексична — наскільки різна лексика заголовків.
    Індекс рахується ВСЕРЕДИНІ кластера, тобто вже після того, як
    ембединги звели різномовні описи однієї події докупи.
    """
    import numpy as np

    items = cluster["items"]
    if len(items) < 2:
        return 0, {}

    vecs = cluster.get("vecs")
    if vecs is not None and len(vecs) > 1:
        centroid = vecs.mean(axis=0)
        n = np.linalg.norm(centroid)
        sims = vecs @ (centroid / n) if n else np.zeros(len(vecs))
        semantic = float(1 - sims.mean())
    else:
        semantic = 0.0

    poles = {i["pole"] for i in items}
    has_state = bool(poles & STATE_POLES)
    has_free = bool(poles - STATE_POLES)
    polar = 1.0 if (has_state and has_free) else (0.5 if len(poles) > 2 else 0.0)

    token_sets = [_tokens(i["title"]) for i in items]
    pairs, overlap = 0, 0.0
    for a in range(len(token_sets)):
        for b in range(a + 1, len(token_sets)):
            ta, tb = token_sets[a], token_sets[b]
            if ta and tb:
                overlap += len(ta & tb) / min(len(ta), len(tb))
                pairs += 1
    lexical = 1 - (overlap / pairs) if pairs else 0.0

    score = 100 * (0.45 * min(1.0, semantic * 2.4)
                   + 0.30 * polar
                   + 0.25 * min(1.0, lexical))
    return round(score), {
        "semantic": round(semantic, 3),
        "poles": sorted(poles),
        "lexical": round(lexical, 2),
        "state_vs_free": has_state and has_free,
    }


def fake_consensus(cluster, owners):
    """Чи не є «підтвердження кількома джерелами» однією редакційною лінією.
    Три видання одного власника — це не три підтвердження."""
    by_owner = Counter()
    for i in cluster["items"]:
        o = owners.get(i["source"], "")
        if o:
            by_owner[o] += 1
    if not by_owner:
        return None
    owner, count = by_owner.most_common(1)[0]
    total = len(cluster["items"])
    if count >= 2 and count / total >= 0.5:
        names = sorted({i["source"] for i in cluster["items"]
                        if owners.get(i["source"]) == owner})
        return f"{count} з {total} джерел належать {owner} ({', '.join(names)})"
    return None

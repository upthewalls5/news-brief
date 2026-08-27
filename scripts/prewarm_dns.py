#!/usr/bin/env python3
"""
prewarm_dns.py — резолвить усі хости через DNS-over-HTTPS і прописує їх у /etc/hosts.

Навіщо: резолвер раннера GitHub не справляється з частиною доменів
(японськими, ізраїльськими, іранськими, українськими). DoH працює поверх
звичайного HTTPS, який точно доступний, тому обходить проблему цілком.
Після цього кроку жоден скрипт уже не залежить від системного DNS.

Запускається у воркфлоу перед discover.py і collect.py.
Помилки не фатальні: не вийшло — працюємо як раніше.

Usage: sudo python scripts/prewarm_dns.py
"""

import asyncio
import csv
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
HOSTS_FILE = "/etc/hosts"
CONCURRENCY = 8

RESOLVERS = [
    ("https://cloudflare-dns.com/dns-query", {"accept": "application/dns-json"}),
    ("https://dns.google/resolve", {"accept": "application/json"}),
]


def collect_hosts():
    """Усі хости з sources.csv (колонка feed) і з feeds.json, якщо він уже є."""
    hosts = set()

    csv_path = ROOT / "sources.csv"
    if csv_path.exists():
        for row in csv.DictReader(csv_path.open(encoding="utf-8")):
            domain = (row.get("domain") or "").strip()
            if domain:
                hosts.add(domain.lstrip("."))
                if not domain.startswith("www."):
                    hosts.add("www." + domain)
            for u in (row.get("feed") or "").split("|"):
                u = u.strip()
                if u:
                    h = urlparse(u).netloc.split(":")[0]
                    if h:
                        hosts.add(h)

    feeds_path = ROOT / "feeds.json"
    if feeds_path.exists():
        try:
            for f in json.loads(feeds_path.read_text(encoding="utf-8")):
                h = urlparse(f.get("feed", "")).netloc.split(":")[0]
                if h:
                    hosts.add(h)
        except Exception:
            pass

    return sorted(h for h in hosts if "." in h)


async def doh_query(client, host, rtype):
    """rtype: "A" (код 1) або "AAAA" (код 28). Повертає адресу або None."""
    want = 1 if rtype == "A" else 28
    for url, headers in RESOLVERS:
        try:
            r = await client.get(url, params={"name": host, "type": rtype},
                                 headers=headers, timeout=12.0)
            if r.status_code != 200:
                continue
            for ans in r.json().get("Answer", []):
                if ans.get("type") == want:
                    return ans["data"]
        except Exception:
            continue
    return None


async def doh_lookup(client, host):
    """Повертає (ipv4, ipv6). У /etc/hosts пишемо IPv4, якщо він є."""
    v4 = await doh_query(client, host, "A")
    v6 = None if v4 else await doh_query(client, host, "AAAA")
    return v4, v6


async def main():
    hosts = collect_hosts()
    print(f"Резолвлю {len(hosts)} хостів через DoH...")

    sem = asyncio.Semaphore(CONCURRENCY)
    resolved = {}
    only_v6 = []

    async with httpx.AsyncClient(http2=False) as client:
        async def one(h):
            async with sem:
                v4, v6 = await doh_lookup(client, h)
                if v4:
                    resolved[h] = v4
                elif v6:
                    only_v6.append(h)
        await asyncio.gather(*(one(h) for h in hosts))

    print(f"Отримано адрес: {len(resolved)} з {len(hosts)}")

    if only_v6:
        print(f"\nЛише IPv6, без IPv4 ({len(only_v6)}): " + ", ".join(only_v6[:25])
              + (" …" if len(only_v6) > 25 else ""))
        print("Ці домени доступні тільки якщо в раннера працює IPv6.")

    missing = [h for h in hosts if h not in resolved and h not in only_v6]
    if missing:
        print(f"Не резолвиться навіть через DoH ({len(missing)}): "
              + ", ".join(missing[:20]) + (" …" if len(missing) > 20 else ""))

    try:
        existing = Path(HOSTS_FILE).read_text(encoding="utf-8")
        block = "\n# --- news-brief DoH prewarm ---\n"
        block += "".join(f"{ip}\t{h}\n" for h, ip in sorted(resolved.items()))
        if "news-brief DoH prewarm" in existing:
            existing = existing.split("# --- news-brief DoH prewarm ---")[0].rstrip() + "\n"
        Path(HOSTS_FILE).write_text(existing + block, encoding="utf-8")
        print(f"Записано в {HOSTS_FILE}: {len(resolved)} записів")
    except PermissionError:
        print("Немає прав на /etc/hosts — запускайте через sudo. Пропускаю.")
    except Exception as exc:
        print(f"Не вдалося записати /etc/hosts: {exc}. Пропускаю.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # Цей крок не має права зупиняти пайплайн
        print(f"prewarm_dns не спрацював: {exc}", file=sys.stderr)

"""OpenAmer-Wachhund: misst die vier Bereiche taeglich.

  1 Eigene Zahlen        GitHub, Hugging Face, Bluesky, Website
  2 Kommentare           Facebook-Gruppe (offene Fragen)
  3 Erwaehnungen         Bluesky-Suche nach "OpenAmer"
  4 Technische Gesundheit Spaces, Website, API-Endpunkte

Laeuft ohne Modellaufruf. Gibt nur dann etwas aus, wenn sich etwas bewegt hat
oder ein Problem auftritt - sonst bleibt der Cron-Lauf still.
"""
import json
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

BASIS = Path(__file__).resolve().parent
STAND = BASIS / "watch_stand.json"
LOG = BASIS / "watch.log"

zeilen = []
def log(t):
    zeilen.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}  {t}")

def flush():
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write("\n".join(zeilen) + "\n")
    except Exception:
        pass

def hole(url, timeout=20, roh=False):
    req = urllib.request.Request(url, headers={"User-Agent": "OpenAmer-Watch"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            d = r.read()
            return d.decode("utf-8", "replace") if roh else json.loads(d.decode())
    except Exception as e:
        return {"_fehler": str(e)[:60]}

def status(url, timeout=15):
    """Nur HTTP-Status und Latenz."""
    import time as _t
    t0 = _t.time()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OpenAmer-Watch"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, round((_t.time() - t0) * 1000)
    except Exception as e:
        return str(e)[:40], round((_t.time() - t0) * 1000)

jetzt = {}
probleme = []

# ============ 1. EIGENE ZAHLEN ============
log("--- eigene Zahlen ---")

# GitHub
gh = hole("https://api.github.com/repos/openamer-max/openamer")
if "_fehler" not in gh:
    jetzt["github_sterne"] = gh.get("stargazers_count", 0)
    jetzt["github_forks"] = gh.get("forks_count", 0)
    log(f"GitHub: {jetzt['github_sterne']} Sterne, {jetzt['github_forks']} Forks")
else:
    probleme.append(f"GitHub-API: {gh['_fehler']}")

ghu = hole("https://api.github.com/users/openamer-max")
if "_fehler" not in ghu:
    jetzt["github_follower"] = ghu.get("followers", 0)
    log(f"GitHub-Follower: {jetzt['github_follower']}")

# Releases-Downloads
rel = hole("https://api.github.com/repos/openamer-max/openamer/releases?per_page=20")
if isinstance(rel, list):
    dl = sum(a.get("download_count", 0) for r in rel for a in r.get("assets", []))
    jetzt["release_downloads"] = dl
    log(f"Release-Downloads: {dl}")

# Hugging Face
m = hole("https://huggingface.co/api/models?author=openamer-max&limit=40")
if isinstance(m, list):
    jetzt["hf_modelle"] = len(m)
    jetzt["hf_downloads"] = sum(x.get("downloads", 0) for x in m)
    jetzt["hf_likes"] = sum(x.get("likes", 0) for x in m)
    log(f"HF: {len(m)} Modelle, {jetzt['hf_downloads']:,} Downloads, {jetzt['hf_likes']} Likes")

ds = hole("https://huggingface.co/api/datasets?author=openamer-max&limit=20")
if isinstance(ds, list):
    jetzt["hf_dataset_downloads"] = sum(x.get("downloads", 0) for x in ds)
    log(f"HF-Datasets: {len(ds)}, {jetzt['hf_dataset_downloads']} Downloads")

# Bluesky
bs = hole("https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=openamer.bsky.social")
if "_fehler" not in bs:
    jetzt["bsky_follower"] = bs.get("followersCount", 0)
    jetzt["bsky_posts"] = bs.get("postsCount", 0)
    log(f"Bluesky: {jetzt['bsky_follower']} Follower, {jetzt['bsky_posts']} Posts")

# ============ 2. ERWAEHNUNGEN ============
log("--- Erwaehnungen ---")
erw = hole("https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=OpenAmer&limit=25")
if "_fehler" not in erw:
    posts = erw.get("posts", [])
    fremde = [p for p in posts
              if "openamer" not in (p.get("author", {}).get("handle", "") or "").lower()]
    jetzt["bsky_erwaehnungen"] = len(fremde)
    log(f"Bluesky-Erwähnungen (fremde): {len(fremde)}")
    if fremde:
        for p in fremde[:3]:
            h = p.get("author", {}).get("handle", "?")
            t = (p.get("record", {}).get("text", "") or "")[:70]
            log(f"  @{h}: {t}")

# ============ 3. TECHNISCHE GESUNDHEIT ============
log("--- Gesundheit ---")
seiten = {
    "Website": "https://openamer-max.github.io/",
    "HF-Modell": "https://huggingface.co/openamer-max/openamer-max",
    "HF-Chat": "https://openamer-max-openamer-chat.hf.space",
    "HF-API": "https://openamer-max-openamer-max-api.hf.space",
    "HF-Translate": "https://openamer-max-openamer-translate.hf.space/health",
    "GitHub": "https://github.com/openamer-max/openamer",
}
for name, url in seiten.items():
    code, ms = status(url)
    jetzt[f"status_{name}"] = code
    # 404 bei HF-Spaces bedeutet meist "schläft" - das ist normal, kein Fehler
    if code == 200:
        log(f"{name:12s} {code}  {ms} ms")
    elif str(code).startswith("404") and name.startswith("HF-"):
        log(f"{name:12s} schläft (404, wacht beim ersten Aufruf auf)")
    else:
        log(f"{name:12s} {code}  {ms} ms")
        probleme.append(f"{name} antwortet {code}")

# GitHub-API-Kontingent
lim = hole("https://api.github.com/rate_limit")
if "_fehler" not in lim:
    kern = lim.get("resources", {}).get("core", {})
    jetzt["gh_api_rest"] = kern.get("remaining", 0)
    log(f"GitHub-API-Kontingent: {jetzt['gh_api_rest']} von {kern.get('limit', 0)}")

# ============ VERGLEICH MIT GESTERN ============
vorher = {}
if STAND.exists():
    try:
        daten = json.loads(STAND.read_text(encoding="utf-8"))
        vorher = daten.get("letzter", {})
    except Exception:
        pass

bewegung = []
for k, v in jetzt.items():
    if k.startswith("status_") or k.startswith("gh_api"):
        continue
    alt = vorher.get(k)
    if isinstance(alt, (int, float)) and isinstance(v, (int, float)):
        d = v - alt
        if d != 0:
            bewegung.append((k, alt, v, d))

STAND.parent.mkdir(parents=True, exist_ok=True)
STAND.write_text(json.dumps({
    "datum": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "letzter": jetzt,
}, indent=2, ensure_ascii=False), encoding="utf-8")

flush()

# ============ AUSGABE (nur bei Bewegung oder Problem) ============
def name(k):
    return {
        "github_sterne": "GitHub-Sterne",
        "github_forks": "Forks",
        "github_follower": "GitHub-Follower",
        "release_downloads": "Release-Downloads",
        "hf_modelle": "HF-Modelle",
        "hf_downloads": "HF-Downloads",
        "hf_likes": "HF-Likes",
        "hf_dataset_downloads": "Dataset-Downloads",
        "bsky_follower": "Bluesky-Follower",
        "bsky_posts": "Bluesky-Posts",
        "bsky_erwaehnungen": "Erwähnungen",
    }.get(k, k)

meldungen = []
if bewegung:
    meldungen.append("Bewegung seit dem letzten Lauf:")
    for k, alt, neu, d in bewegung:
        zeichen = "+" if d > 0 else ""
        meldungen.append(f"  {name(k):20s} {alt:,} → {neu:,}   ({zeichen}{d})")

if probleme:
    meldungen.append("")
    meldungen.append(f"{len(probleme)} Problem(e):")
    for p in probleme:
        meldungen.append(f"  · {p}")

if meldungen:
    print("\n".join(meldungen))

"""Test: can we get the song tracklist for the latest BBC Music Introducing Mixtape episode?

Tries several BBC endpoints and writes everything it finds to out/ plus a summary.
Run by .github/workflows/tracklist-test.yml. Read only; changes nothing in the repo.
"""
import datetime as dt
import email.utils
import json
import os
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

APPLE_ID = "269455899"
UA = "Mozilla/5.0 (personal tracklist test; github.com/TRTools/bbc-introducing)"
OUT = "out"
os.makedirs(OUT, exist_ok=True)
log_lines = []


def log(msg):
    print(msg)
    log_lines.append(msg)


def get(url, name=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json, */*"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        body, status = e.read(), e.code
    except Exception as e:  # network error
        log(f"  FAIL {url} -> {type(e).__name__}: {e}")
        return None, None
    log(f"  {status} {url} ({len(body)} bytes)")
    if name:
        with open(os.path.join(OUT, name), "wb") as f:
            f.write(body)
    return status, body


def as_json(body):
    try:
        return json.loads(body)
    except Exception:
        return None


def find_tracks(obj):
    """Walk any JSON and collect things that look like music segments."""
    found = []

    def walk(o):
        if isinstance(o, dict):
            titles = o.get("titles") if isinstance(o.get("titles"), dict) else None
            if titles and ("primary" in titles or "secondary" in titles) and (
                o.get("type") in ("segment_item", "music") or "segment_type" in o or "offset" in o
            ):
                found.append({"artist": titles.get("primary"), "title": titles.get("secondary"),
                              "offset": (o.get("offset") or {}).get("start") if isinstance(o.get("offset"), dict) else o.get("offset")})
            seg = o.get("segment") if isinstance(o.get("segment"), dict) else None
            if seg and seg.get("type") == "music":
                found.append({"artist": seg.get("artist"), "title": seg.get("track_title") or seg.get("title"),
                              "offset": o.get("version_offset")})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return found


results = {}

log("STEP 1: podcast feed URL from Apple lookup")
_, body = get(f"https://itunes.apple.com/lookup?id={APPLE_ID}&entity=podcast", "apple_lookup.json")
feed_url = None
if body and as_json(body):
    res = as_json(body).get("results") or [{}]
    feed_url = res[0].get("feedUrl")
log(f"  feedUrl = {feed_url}")

log("STEP 2: latest episode in the RSS feed")
item_info = {}
if feed_url:
    _, body = get(feed_url, "feed.xml")
    if body:
        root = ET.fromstring(body)
        item = root.find("./channel/item")
        if item is not None:
            for tag in ("title", "link", "guid", "pubDate", "description"):
                el = item.find(tag)
                item_info[tag] = (el.text or "").strip() if el is not None else None
            enc = item.find("enclosure")
            item_info["enclosure"] = enc.get("url") if enc is not None else None
log("  " + json.dumps(item_info, ensure_ascii=False)[:800])

pids = set()
for v in item_info.values():
    for m in re.findall(r"\b([bmpw][0-9a-z]{7})\b", v or ""):
        pids.add(m)
log(f"  candidate pids from feed item: {sorted(pids)}")

log("STEP 3: programme JSON and segments for each pid")
vpids = set()
for pid in sorted(pids):
    st, body = get(f"https://www.bbc.co.uk/programmes/{pid}.json", f"prog_{pid}.json")
    j = as_json(body) if body else None
    if j:
        prog = j.get("programme", {})
        log(f"    type={prog.get('type')} title={prog.get('title')} parent={((prog.get('parent') or {}).get('programme') or {}).get('pid')}")
        for v in prog.get("versions", []) or []:
            if v.get("pid"):
                vpids.add(v["pid"])
    st, body = get(f"https://www.bbc.co.uk/programmes/{pid}/segments.json", f"seg_{pid}.json")
    j = as_json(body) if body else None
    if j:
        results[f"programmes/{pid}/segments.json"] = find_tracks(j)
    st, body = get(f"https://rms.api.bbc.co.uk/v2/programmes/{pid}/playable", f"rms_playable_{pid}.json")
    j = as_json(body) if body else None
    if j:
        for m in re.findall(r'"([bmpw][0-9a-z]{7})"', json.dumps(j)):
            pass
        for key in ("version_id", "vpid"):
            for m in re.findall(rf'"{key}"\s*:\s*"([0-9a-z]{{8}})"', json.dumps(j)):
                vpids.add(m)

for vpid in sorted(vpids):
    st, body = get(f"https://rms.api.bbc.co.uk/v2/versions/{vpid}/segments", f"rms_seg_{vpid}.json")
    j = as_json(body) if body else None
    if j:
        results[f"rms versions/{vpid}/segments"] = find_tracks(j)

log("STEP 4: 6 Music schedule around the release date (the radio broadcast)")
pub = None
if item_info.get("pubDate"):
    try:
        pub = email.utils.parsedate_to_datetime(item_info["pubDate"]).date()
    except Exception:
        pub = None
pub = pub or dt.date.today()
for d in [pub + dt.timedelta(days=i) for i in range(-1, 5)]:
    st, body = get(f"https://rms.api.bbc.co.uk/v2/broadcasts/schedules/bbc_6music/{d.isoformat()}",
                   f"sched_{d.isoformat()}.json")
    j = as_json(body) if body else None
    if not j:
        continue
    for b in j.get("data", []):
        t = json.dumps(b.get("titles", {}))
        if "Introducing" in t or "Mixtape" in t:
            ep_pid = (b.get("programme") or {}).get("id") or b.get("episode_id")
            log(f"    {d}: {t[:160]} episode={ep_pid} broadcast={b.get('id')}")
            for m in re.findall(r'"([bmpw][0-9a-z]{7})"', json.dumps(b)):
                if m not in pids:
                    pids.add(m)
                    st2, body2 = get(f"https://www.bbc.co.uk/programmes/{m}/segments.json", f"seg_{m}.json")
                    j2 = as_json(body2) if body2 else None
                    if j2:
                        results[f"programmes/{m}/segments.json"] = find_tracks(j2)

log("RESULT")
best = max(results.items(), key=lambda kv: len(kv[1]), default=(None, []))
for src, tracks in results.items():
    log(f"  {src}: {len(tracks)} tracks")
if best[1]:
    log(f"  BEST: {best[0]}")
    for i, t in enumerate(best[1], 1):
        log(f"   {i:2}. {t.get('artist')} - {t.get('title')}  (offset {t.get('offset')})")
else:
    log("  No tracklist found. See the out/ files in the run artifact.")

with open(os.path.join(OUT, "summary.json"), "w") as f:
    json.dump({"episode": item_info, "results": results}, f, ensure_ascii=False, indent=1)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a") as f:
        f.write("```\n" + "\n".join(log_lines) + "\n```\n")

#!/usr/bin/env python3
"""
Personal Internship Aggregator -- ingestion pipeline.

Fetches postings from:
  1. Community GitHub trackers (structured listings.json, or README markdown table fallback)
  2. Target-company ATS feeds (Greenhouse / Lever / Ashby public JSON)

Normalizes everything into one schema, deduplicates across sources, filters to
what's relevant, preserves a stable `first_seen` per posting, and writes
../data/postings.json for the static site to read.

Design notes:
  * One broken source must NOT break the build. Every source is wrapped in
    try/except; failures are logged into the output's `sources` block.
  * GitHub fetches use ETag conditional requests (cache/ in this dir) to be
    polite to rate limits and skip unchanged downloads.
  * No database. State that must survive (first_seen) lives in postings.json.

Run:  python ingest.py
"""

import json
import os
import re
import sys
import time
import html
import hashlib
import datetime as dt
from urllib.parse import urlparse

import requests

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_DIR = os.path.join(ROOT, "config")
DATA_DIR = os.path.join(ROOT, "data")
CACHE_DIR = os.path.join(HERE, "cache")
OUT_FILE = os.path.join(DATA_DIR, "postings.json")

USER_AGENT = "intern-feed/1.0 (+personal aggregator; consumes public job JSON)"
TIMEOUT = 30

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)


def log(msg):
    print(f"[ingest] {msg}", flush=True)


def now_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:  # noqa
        log(f"WARN could not read {path}: {e}")
        return default


# --------------------------------------------------------------------------- #
# HTTP with ETag caching
# --------------------------------------------------------------------------- #
def _cache_paths(key):
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return (os.path.join(CACHE_DIR, h + ".meta.json"),
            os.path.join(CACHE_DIR, h + ".body"))


def fetch(url, cache=True):
    """GET a URL. Uses ETag conditional requests when cache=True.
    Returns response text (str). Raises on hard failure."""
    headers = {"User-Agent": USER_AGENT}
    meta_path, body_path = _cache_paths(url)
    meta = load_json(meta_path, {}) if cache else {}
    if cache and meta.get("etag") and os.path.exists(body_path):
        headers["If-None-Match"] = meta["etag"]

    r = requests.get(url, headers=headers, timeout=TIMEOUT)
    if r.status_code == 304 and os.path.exists(body_path):
        log(f"304 (cached) {url}")
        with open(body_path, "r", encoding="utf-8") as f:
            return f.read()
    r.raise_for_status()
    text = r.text
    if cache:
        etag = r.headers.get("ETag")
        if etag:
            with open(body_path, "w", encoding="utf-8") as f:
                f.write(text)
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({"etag": etag, "url": url, "at": now_iso()}, f)
    return text


def fetch_json(url, cache=True):
    return json.loads(fetch(url, cache=cache))


# --------------------------------------------------------------------------- #
# Classification helpers
# --------------------------------------------------------------------------- #
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF‍️]+"
)
US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY","DC",
}
INTL_HINTS = [
    "hong kong", "singapore", "london", "united kingdom", "uk", "china",
    "india", "canada", "toronto", "vancouver", "ireland", "dublin", "amsterdam",
    "netherlands", "germany", "berlin", "munich", "france", "paris", "tokyo",
    "japan", "korea", "seoul", "australia", "sydney", "tel aviv", "israel",
    "zurich", "switzerland", "shanghai", "beijing", "shenzhen", "taiwan",
    "bangalore", "hyderabad", "pune", "mexico", "brazil", "poland", "warsaw",
]
ASIA_HK_HINTS = ["hong kong", "singapore", "china", "shanghai", "beijing",
                 "shenzhen", "taiwan", "tokyo", "japan", "korea", "seoul",
                 "india", "bangalore", "hyderabad", "pune"]

CAT_RULES = [
    ("quant", ["quant", "trading", "trader", "quantitative"]),
    ("ml", ["machine learning", " ml ", "ml ", " ml", "deep learning",
            "artificial intelligence", " ai ", "ai/", "/ai", "nlp",
            "computer vision", "research scientist", "research engineer",
            "data scien", "applied scien", "ai resident", "llm"]),
    ("hardware", ["hardware", "asic", "fpga", "rtl", "vlsi", "chip", "silicon",
                  "embedded", "electrical eng", "firmware", "circuit",
                  "semiconductor", "verification eng", "physical design"]),
    ("swe", ["software", "swe", "developer", "engineer", "full stack",
             "full-stack", "frontend", "front end", "backend", "back end",
             "programmer", "infrastructure", "platform", "systems", "ios",
             "android", "web", "devops", "site reliability", "sre"]),
]
EARLY_RE = re.compile(
    r"\b(sophomore|freshman|first[- ]?year|1st[- ]?year|2nd[- ]?year|"
    r"second[- ]?year|underclass|early career|early-career)\b", re.I)


def strip_emoji(s):
    return EMOJI_RE.sub("", s or "").strip()


def classify_category(title):
    t = " " + (title or "").lower() + " "
    for cat, kws in CAT_RULES:
        for kw in kws:
            if kw in t:
                return cat
    return "other"


def looks_intern(title):
    t = (title or "").lower()
    return any(k in t for k in (
        "intern", "co-op", "coop", "student", "sophomore", "freshman",
        "new grad", "new-grad", "university grad", "campus"))


def region_for(locations):
    """Return ('us'|'remote'|'intl'|'unknown', is_remote, is_asia_hk)."""
    locs = [l.lower() for l in (locations or []) if l]
    blob = " | ".join(locs)
    is_remote = "remote" in blob
    is_asia_hk = any(h in blob for h in ASIA_HK_HINTS)
    is_intl = any(h in blob for h in INTL_HINTS)
    # US if any location has a US state code token or says united states / usa
    is_us = False
    for l in locs:
        if "united states" in l or "usa" in l or l.strip().endswith(", us"):
            is_us = True
        for tok in re.split(r"[ ,/()]+", l.upper()):
            if tok in US_STATES:
                is_us = True
    if is_us:
        return ("us", is_remote, is_asia_hk)
    if is_remote and not is_intl:
        return ("remote", True, is_asia_hk)
    if is_intl:
        return ("intl", is_remote, is_asia_hk)
    if not locs:
        return ("unknown", is_remote, is_asia_hk)
    return ("unknown", is_remote, is_asia_hk)


def to_iso_date(value):
    """Accept unix seconds/ms, ISO string, or None -> ISO date string or None."""
    if value in (None, "", 0):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v > 1e12:  # ms
            v /= 1000.0
        try:
            return dt.datetime.fromtimestamp(v, dt.timezone.utc).replace(
                microsecond=0).isoformat()
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        try:
            s2 = s.replace("Z", "+00:00")
            return dt.datetime.fromisoformat(s2).replace(
                microsecond=0).astimezone(dt.timezone.utc).isoformat()
        except Exception:
            return s  # leave as-is; better than dropping
    return None


# --------------------------------------------------------------------------- #
# Normalization into the unified posting record
# --------------------------------------------------------------------------- #
def make_posting(company, title, locations, apply_url, posted_date, season,
                 sponsorship, source_label, active=True):
    locations = [l for l in (locations or []) if l]
    category = classify_category(title)
    region, is_remote, is_asia_hk = region_for(locations)
    return {
        "company": (company or "").strip(),
        "role_title": (title or "").strip(),
        "location": locations,
        "posted_date": to_iso_date(posted_date),
        "apply_url": (apply_url or "").strip(),
        "season": season or "",
        "sponsorship": sponsorship or "",
        "category": category,
        "region": region,
        "is_remote": is_remote,
        "is_asia_hk": is_asia_hk,
        "early_career": bool(EARLY_RE.search(title or "")),
        "active": bool(active),
        "sources": [source_label],
        # first_seen filled in later (after dedupe + merge with previous run)
    }


# --------------------------------------------------------------------------- #
# Source: GitHub repo with structured listings.json
# --------------------------------------------------------------------------- #
def ingest_repo_json(repo):
    raw = (f"https://raw.githubusercontent.com/{repo['name']}/"
           f"{repo['branch']}/{repo['json_path']}")
    data = fetch_json(raw)
    out = []
    for it in data:
        if not isinstance(it, dict):
            continue
        # Hidden/inactive listings still ingested but flagged; UI can filter.
        if it.get("is_visible") is False:
            continue
        out.append(make_posting(
            company=it.get("company_name"),
            title=it.get("title"),
            locations=it.get("locations") or [],
            apply_url=it.get("url"),
            posted_date=it.get("date_posted") or it.get("date_updated"),
            season=it.get("season"),
            sponsorship=it.get("sponsorship"),
            source_label=repo["source_label"],
            active=it.get("active", True),
        ))
    return out


# --------------------------------------------------------------------------- #
# Source: GitHub repo, README markdown table fallback
# --------------------------------------------------------------------------- #
APPLY_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def _clean_cell(cell):
    # turn [text](url) into text, drop stray markdown, strip emoji/space
    cell = MD_LINK_RE.sub(r"\1", cell)
    cell = cell.replace("**", "").replace("`", "")
    return strip_emoji(cell).strip()


def ingest_repo_readme(repo):
    raw = (f"https://raw.githubusercontent.com/{repo['name']}/"
           f"{repo['branch']}/{repo['readme_path']}")
    text = fetch(raw)
    section = repo.get("readme_section", "the list").lower()

    # isolate the target section (## the list ... up to next ## heading)
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().lower().lstrip("#").strip() == section and ln.lstrip().startswith("#"):
            start = i
            break
    if start is None:
        start = 0
    block = []
    for ln in lines[start + 1:]:
        if ln.lstrip().startswith("## "):
            break
        block.append(ln)

    out = []
    for ln in block:
        if not ln.strip().startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        joined = " ".join(cells).lower()
        if set(joined.replace(" ", "")) <= set("-:"):  # separator row
            continue
        if cells[0].lower() in ("company", "org", "program") and "role" in joined:
            continue  # header row
        company = _clean_cell(cells[0])
        role_raw = cells[1]
        role = _clean_cell(role_raw)
        location = _clean_cell(cells[2])
        # apply url from the last cell(s)
        m = APPLY_LINK_RE.search(cells[3]) or APPLY_LINK_RE.search(ln)
        apply_url = m.group(1) if m else ""
        if not company or not apply_url:
            continue
        closed = "🔒" in role_raw or "closed" in role_raw.lower()
        spons = "Does Not Offer Sponsorship" if "🛂" in role_raw else (
            "U.S. Citizenship Required" if "🇺🇸" in role_raw else "")
        out.append(make_posting(
            company=company,
            title=role,
            locations=[location] if location else [],
            apply_url=apply_url,
            posted_date=None,           # README table carries no dates
            season="",
            sponsorship=spons,
            source_label=repo["source_label"],
            active=not closed,
        ))
    return out


# --------------------------------------------------------------------------- #
# Source: ATS feeds
# --------------------------------------------------------------------------- #
def ingest_greenhouse(company):
    token = company["token"]
    url = (f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
           f"?content=false")
    data = fetch_json(url, cache=False)
    out = []
    for j in data.get("jobs", []):
        title = j.get("title", "")
        locs = []
        if j.get("location", {}).get("name"):
            locs = [j["location"]["name"]]
        for off in j.get("offices", []) or []:
            if off.get("name"):
                locs.append(off["name"])
        out.append(make_posting(
            company=company["name"],
            title=title,
            locations=locs,
            apply_url=j.get("absolute_url"),
            posted_date=j.get("updated_at") or j.get("first_published"),
            season="",
            sponsorship="",
            source_label=company["name"],
            active=True,
        ))
    return out


def ingest_lever(company):
    token = company["token"]
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    data = fetch_json(url, cache=False)
    out = []
    for j in data:
        cats = j.get("categories", {}) or {}
        loc = cats.get("location")
        out.append(make_posting(
            company=company["name"],
            title=j.get("text", ""),
            locations=[loc] if loc else [],
            apply_url=j.get("hostedUrl") or j.get("applyUrl"),
            posted_date=j.get("createdAt"),
            season="",
            sponsorship="",
            source_label=company["name"],
            active=True,
        ))
    return out


def ingest_ashby(company):
    token = company["token"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    data = fetch_json(url, cache=False)
    out = []
    for j in data.get("jobs", []):
        loc = j.get("location")
        locs = [loc] if loc else []
        for sl in j.get("secondaryLocations", []) or []:
            if sl.get("location"):
                locs.append(sl["location"])
        out.append(make_posting(
            company=company["name"],
            title=j.get("title", ""),
            locations=locs,
            apply_url=j.get("jobUrl") or j.get("applyUrl"),
            posted_date=j.get("publishedAt") or j.get("updatedAt"),
            season="",
            sponsorship="",
            source_label=company["name"],
            active=(j.get("isListed", True)),
        ))
    return out


ATS_FUNCS = {
    "greenhouse": ingest_greenhouse,
    "lever": ingest_lever,
    "ashby": ingest_ashby,
}


# --------------------------------------------------------------------------- #
# Dedupe + filter
# --------------------------------------------------------------------------- #
def norm_company(name):
    n = strip_emoji(name).lower()
    n = re.sub(r"\(.*?\)", " ", n)            # drop parentheticals e.g. (SIG)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


SEASON_WORDS = ("summer", "winter", "fall", "spring", "autumn")


def norm_title(title):
    t = strip_emoji(title).lower()
    t = re.sub(r"20\d{2}", " ", t)            # drop years
    for w in SEASON_WORDS:
        t = t.replace(w, " ")
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def host_of(url):
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def dedupe(postings):
    merged = {}
    order = []
    for p in postings:
        key = f"{norm_company(p['company'])}|{norm_title(p['role_title'])}|{host_of(p['apply_url'])}"
        if key not in merged:
            merged[key] = p
            order.append(key)
        else:
            ex = merged[key]
            for s in p["sources"]:
                if s not in ex["sources"]:
                    ex["sources"].append(s)
            # union locations
            for loc in p["location"]:
                if loc not in ex["location"]:
                    ex["location"].append(loc)
            # keep earliest known posted_date
            if p["posted_date"] and (not ex["posted_date"]
                                     or p["posted_date"] < ex["posted_date"]):
                ex["posted_date"] = p["posted_date"]
            # recompute region now that locations may have grown
            ex["region"], ex["is_remote"], ex["is_asia_hk"] = region_for(ex["location"])
    return [merged[k] for k in order]


def passes_filter(p, filters):
    if p["category"] not in set(filters.get("categories", [])):
        return False
    if not filters.get("include_intl", True) and p["region"] == "intl":
        return False
    if not filters.get("include_remote", True) and p["region"] == "remote":
        return False
    return True


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    repos_cfg = load_json(os.path.join(CONFIG_DIR, "repos.json"), {}) or {}
    comps_cfg = load_json(os.path.join(CONFIG_DIR, "companies.json"), {}) or {}
    filters = load_json(os.path.join(CONFIG_DIR, "filters.json"), {}) or {}

    source_status = []
    raw = []

    # ---- GitHub repos -----------------------------------------------------
    for repo in repos_cfg.get("repos", []):
        label = repo.get("source_label", repo.get("name"))
        try:
            if repo.get("type") == "json":
                items = ingest_repo_json(repo)
            elif repo.get("type") == "readme":
                items = ingest_repo_readme(repo)
            else:
                raise ValueError(f"unknown repo type {repo.get('type')}")
            raw.extend(items)
            source_status.append({"name": label, "kind": "repo",
                                  "status": "ok", "count": len(items)})
            log(f"OK repo {label}: {len(items)} raw")
        except Exception as e:  # noqa
            source_status.append({"name": label, "kind": "repo",
                                  "status": "error", "count": 0,
                                  "error": f"{type(e).__name__}: {e}"})
            log(f"ERROR repo {label}: {e}")

    # ---- Target company ATS ----------------------------------------------
    require_intern = filters.get("require_intern_keyword_for_ats", True)
    for c in comps_cfg.get("companies", []):
        ats = c.get("ats")
        if ats in (None, "calendar-only"):
            source_status.append({"name": c["name"], "kind": "ats",
                                  "status": "calendar-only", "count": 0,
                                  "note": c.get("note", "")})
            continue
        fn = ATS_FUNCS.get(ats)
        if not fn:
            source_status.append({"name": c["name"], "kind": "ats",
                                  "status": "error", "count": 0,
                                  "error": f"unknown ats {ats}"})
            continue
        try:
            items = fn(c)
            if require_intern:
                items = [p for p in items if looks_intern(p["role_title"])]
            raw.extend(items)
            source_status.append({"name": c["name"], "kind": "ats",
                                  "status": "ok", "count": len(items),
                                  "ats": ats})
            log(f"OK ats {c['name']} ({ats}): {len(items)} intern roles")
        except Exception as e:  # noqa
            source_status.append({"name": c["name"], "kind": "ats",
                                  "status": "error", "count": 0,
                                  "ats": ats,
                                  "error": f"{type(e).__name__}: {e}"})
            log(f"ERROR ats {c['name']}: {e}")

    log(f"raw postings collected: {len(raw)}")

    # ---- Dedupe -----------------------------------------------------------
    deduped = dedupe(raw)
    log(f"after dedupe: {len(deduped)}")

    # ---- Filter -----------------------------------------------------------
    kept = [p for p in deduped if passes_filter(p, filters)]
    log(f"after filter: {len(kept)}")

    # ---- first_seen persistence ------------------------------------------
    prev = load_json(OUT_FILE, {}) or {}
    prev_first = {}
    for p in prev.get("postings", []):
        k = f"{norm_company(p['company'])}|{norm_title(p['role_title'])}|{host_of(p['apply_url'])}"
        prev_first[k] = p.get("first_seen")
    seen_now = now_iso()
    new_count = 0
    for p in kept:
        k = f"{norm_company(p['company'])}|{norm_title(p['role_title'])}|{host_of(p['apply_url'])}"
        p["id"] = hashlib.sha1(k.encode("utf-8")).hexdigest()[:12]
        if prev_first.get(k):
            p["first_seen"] = prev_first[k]
        else:
            p["first_seen"] = seen_now
            new_count += 1

    # newest first_seen first; tie-break on posted_date
    kept.sort(key=lambda p: (p.get("first_seen") or "", p.get("posted_date") or ""),
              reverse=True)

    out = {
        "generated_at": seen_now,
        "counts": {
            "total": len(kept),
            "new_this_run": new_count,
            "raw": len(raw),
            "deduped": len(deduped),
        },
        "filters": filters,
        "sources": source_status,
        "postings": kept,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    log(f"wrote {OUT_FILE}: {len(kept)} postings ({new_count} new this run)")

    # Non-zero exit only if literally every source failed (so CI can alert),
    # but still write whatever we have.
    oks = [s for s in source_status if s["status"] == "ok"]
    if not oks:
        log("FATAL: no source succeeded")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

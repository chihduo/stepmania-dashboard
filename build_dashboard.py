#!/usr/bin/env python3
"""
Build a StepMania play-activity dashboard from a StepMania 5.1 'Save' folder.

Reads:
  <save>/MachineProfile/Stats.xml   -> authoritative aggregates + per-song play counts
  <save>/Upload/*.xml               -> per-play event log (exact timestamps)

Writes:
  <out>/data.json                   -> everything the dashboard needs
  <out>/index.html                  -> copy of the dashboard page (from this dir)

Usage:
  python3 build_dashboard.py [SAVE_DIR] [OUT_DIR]
  defaults: SAVE_DIR=./savedata/Save (relative to repo) , OUT_DIR=./dashboard/public
"""
import sys, os, glob, json, collections, datetime, shutil, re, struct, hashlib
import xml.etree.ElementTree as ET
try:
    from PIL import Image
except ImportError:
    Image = None  # banner conversion will be skipped

# StepMania occasionally writes invalid XML: raw '&' in song dirs and non-UTF-8
# bytes from odd folder names. Sanitize before parsing.
_AMP = re.compile(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)')
_CTRL = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F]')  # invalid XML 1.0 chars (keep \t\n\r)


def load_xml(path):
    """Parse possibly-malformed StepMania XML; returns the root Element."""
    s = open(path, "rb").read().decode("utf-8", errors="replace")
    s = _AMP.sub("&amp;", s)
    s = _CTRL.sub("", s)
    return ET.fromstring(s)

HERE = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "savedata", "Save")
OUT_DIR  = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "public")

# StepMania default-theme grade tiers -> friendly letters (theme-dependent; best effort).
GRADE_MAP = {
    "Tier01": "AAAA", "Tier02": "AAA", "Tier03": "AA", "Tier04": "A",
    "Tier05": "B", "Tier06": "C", "Tier07": "D", "Failed": "F", "NoData": "-",
}
DIFF_ORDER = ["Beginner", "Easy", "Medium", "Hard", "Challenge", "Edit"]

# Visual config — colors for the combo chart. Loaded from config.json next to
# this script; missing keys fall back to these defaults (deep-merge).
DEFAULT_CONFIG = {
    "colors": {
        "bars": {
            "plays": "#a4b8d4",          # light gray-blue
            "distinctSongs": "#5c7593",  # darker gray-blue
        },
        "lines": {
            "accuracy": "#37e0ff",
            "w1": "#ffcc55",
            "miss": "#ff6b6b",
        },
    },
}


def deep_merge(base, override):
    """Recursive dict merge — override wins on leaf keys."""
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    path = os.path.join(HERE, "config.json")
    cfg = DEFAULT_CONFIG
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                user = json.load(f)
            user.pop("comment", None)  # ignore comment field if present
            cfg = deep_merge(DEFAULT_CONFIG, user)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: config.json unreadable ({e}); using defaults.")
    return cfg


# Grades to hide from the ranking list and recent plays (D and below).
# Only affects those two lists — KPIs, timeline and breakdown charts keep all plays.
EXCLUDE_GRADES = {"Tier07", "Failed"}  # D, F


def txt(node, tag, default=""):
    if node is None:
        return default
    v = node.findtext(tag)
    return v if v is not None else default


def fnum(s, default=0.0):
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def inum(s, default=0):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return default


def song_parts(d):
    """Return (pack, song_folder_name) from a 'Songs/Pack/SongFolder/' dir string."""
    p = d.strip().rstrip("/")
    parts = [x for x in p.split("/") if x]
    if not parts:
        return ("(unknown)", "(unknown)")
    if parts[0].lower() == "songs":
        parts = parts[1:]
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    if len(parts) == 1:
        return ("(loose)", parts[0])
    return ("(unknown)", "(unknown)")


# --- Song metadata (artist/title) from StepMania's song cache ----------------
# StepMania caches each song's tags in Cache/Songs/<mangled-dir> (SSC format).
# The filename is the song Dir with leading/trailing '/' stripped and '/' plus a
# set of invalid UTF-8 lead bytes replaced by '_' (see SongCacheIndex::GetCacheFilePath).
_INVALID_CACHE = set("/") | {chr(b) for b in
    (0xc0, 0xc1, 0xf5, 0xf6, 0xf7, 0xf8, 0xf9, 0xfa, 0xfb, 0xfc, 0xfd, 0xfe, 0xff)}


def cache_filename(d):
    s = d
    if s.startswith("/"):
        s = s[1:]
    if s.endswith("/"):
        s = s[:-1]
    return "".join("_" if c in _INVALID_CACHE else c for c in s)


def make_meta_lookup(cache_songs_dir):
    """Return get(dir)->{'artist','title'}, memoized, reading the SSC cache.

    Lookup is case-insensitive: recorded song dirs sometimes differ in case from
    the on-disk cache filename (e.g. 'DDR K-POP' vs 'DDR K-Pop'), and Linux is
    case-sensitive while the original Windows filesystem was not.
    """
    memo = {}
    stats = {"hit": 0, "miss": 0}
    # index: lowercased cache filename -> actual filename
    index = {}
    if cache_songs_dir and os.path.isdir(cache_songs_dir):
        for fn in os.listdir(cache_songs_dir):
            index[fn.lower()] = fn

    def tag(text, name):
        m = re.search(r"#" + name + r":(.*?);", text, re.S)
        return m.group(1).strip() if m else ""

    def get(d):
        if d in memo:
            return memo[d]
        meta = {"artist": "", "title": ""}
        if index:
            fn = index.get(cache_filename(d).lower())
            if fn:
                text = open(os.path.join(cache_songs_dir, fn), "rb").read().decode("utf-8", errors="replace")
                meta["artist"] = tag(text, "ARTIST") or tag(text, "ARTISTTRANSLIT")
                meta["title"] = tag(text, "TITLE") or tag(text, "TITLETRANSLIT")
                stats["hit"] += 1
            else:
                stats["miss"] += 1
        memo[d] = meta
        return meta

    get.stats = stats
    return get


# --------------------------------------------------------------------------
# 1) Stats.xml : GeneralData aggregates + SongScores (authoritative play counts)
# --------------------------------------------------------------------------
def parse_stats(stats_path, meta, banner=lambda d: ""):
    root = load_xml(stats_path)
    gd = root.find("GeneralData")

    totals = {
        "sessions": inum(txt(gd, "TotalSessions")),
        "sessionSeconds": inum(txt(gd, "TotalSessionSeconds")),
        "gameplaySeconds": inum(txt(gd, "TotalGameplaySeconds")),
        "calories": round(fnum(txt(gd, "TotalCaloriesBurned")), 1),
        "dancePoints": inum(txt(gd, "TotalDancePoints")),
        "songsPlayed": inum(txt(gd, "NumTotalSongsPlayed")),
        "tapsAndHolds": inum(txt(gd, "TotalTapsAndHolds")),
        "jumps": inum(txt(gd, "TotalJumps")),
        "holds": inum(txt(gd, "TotalHolds")),
        "rolls": inum(txt(gd, "TotalRolls")),
        "mines": inum(txt(gd, "TotalMines")),
        "hands": inum(txt(gd, "TotalHands")),
        "lifts": inum(txt(gd, "TotalLifts")),
    }
    profile = {
        "displayName": txt(gd, "DisplayName"),
        "guid": txt(gd, "Guid"),
        "lastPlayed": txt(gd, "LastPlayedDate"),
        "isMachine": txt(gd, "IsMachine") == "1",
    }

    def kv_section(tag, keymap=None):
        node = gd.find(tag) if gd is not None else None
        out = {}
        if node is not None:
            for c in node:
                out[c.tag] = inum(c.text)
        return out

    by_difficulty = kv_section("NumSongsPlayedByDifficulty")
    by_grade = kv_section("NumStagesPassedByGrade")

    by_style = []
    bs = gd.find("NumSongsPlayedByStyle") if gd is not None else None
    if bs is not None:
        for c in bs:
            g = c.get("Game", ""); st = c.get("Style", "")
            label = f"{g}-{st}".strip("-") or c.tag
            by_style.append({"label": label, "count": inum(c.text)})
    by_style.sort(key=lambda x: -x["count"])

    # Daily calories (CalorieData is a child of <Stats>, not <GeneralData>)
    cal = []
    cd = root.find("CalorieData")
    if cd is not None:
        for c in cd.findall("CaloriesBurned"):
            cal.append((c.get("Date", ""), round(fnum(c.text), 1)))
    cal.sort()

    # SongScores -> per song aggregate
    songs = []
    pack_plays = collections.Counter()
    pack_songs = collections.Counter()
    ss = root.find("SongScores")
    if ss is not None:
        for s in ss.findall("Song"):
            d = s.get("Dir", "")
            # Skip theme-internal placeholders / empty dirs (not real songs)
            if not d.startswith("Songs/"):
                continue
            pack, name = song_parts(d)
            plays = 0
            last = ""
            best_pct = None
            best_grade = None
            diffs = {}
            for st in s.findall("Steps"):
                diff = st.get("Difficulty", "?")
                hsl = st.find("HighScoreList")
                n = inum(txt(hsl, "NumTimesPlayed"))
                plays += n
                diffs[diff] = diffs.get(diff, 0) + n
                lp = txt(hsl, "LastPlayed")
                if lp > last:
                    last = lp
                # best score across this song's charts
                for hs in (hsl.findall("HighScore") if hsl is not None else []):
                    pct = fnum(txt(hs, "PercentDP"), -1)
                    if pct >= 0 and (best_pct is None or pct > best_pct):
                        best_pct = pct
                        best_grade = txt(hs, "Grade")
            if plays <= 0:
                continue
            m = meta(d)
            songs.append({
                "song": m["title"] or name, "artist": m["artist"], "pack": pack,
                "dir": d, "plays": plays,
                "banner": banner(d),
                "last": last,
                "bestPct": round(best_pct, 4) if best_pct is not None else None,
                "bestGrade": best_grade or "",
                "diffs": diffs,
            })
            pack_plays[pack] += plays
            pack_songs[pack] += 1

    songs.sort(key=lambda x: (-x["plays"], x["song"].lower()))
    # Packs are computed from all songs above; only the ranking list drops D/F.
    packs = [{"pack": p, "plays": pack_plays[p], "songs": pack_songs[p]}
             for p in pack_plays]
    packs.sort(key=lambda x: -x["plays"])
    all_song_count = len(songs)
    songs = [s for s in songs if (s["bestGrade"] or "") not in EXCLUDE_GRADES]

    return {
        "profile": profile, "totals": totals,
        "byDifficulty": by_difficulty, "byGrade": by_grade, "byStyle": by_style,
        "calorieSeries": cal, "songs": songs, "packs": packs,
        "distinctSongs": all_song_count,
    }


# --------------------------------------------------------------------------
# 2) Upload/*.xml : per-play event log (exact timestamps)
# --------------------------------------------------------------------------
def parse_uploads(upload_dir, meta, banner=lambda d: ""):
    files = sorted(glob.glob(os.path.join(upload_dir, "*.xml")))
    daily = collections.Counter()
    monthly = collections.Counter()
    monthly_cal = collections.Counter()  # not in uploads; left for parity
    # Per-month skill aggregates for the combo chart.
    # Accuracy = mean(PercentDP) per play (so each play weighted equally).
    # W1% and Miss% = note-count-weighted (sum_w1 / sum_total_hits) so a long
    # song doesn't get drowned out by ten short ones.
    m_pct_sum = collections.Counter()
    m_pct_n   = collections.Counter()
    m_w1   = collections.Counter()
    m_miss = collections.Counter()
    m_taps = collections.Counter()
    m_dirs = collections.defaultdict(set)   # distinct song dirs per month
    hour = [0] * 24
    dow = [0] * 7
    recent = []  # keep all, trim later
    total = 0
    first = last = None
    for f in files:
        try:
            root = load_xml(f)
        except ET.ParseError:
            continue
        for h in root.findall(".//HighScoreForASongAndSteps"):
            song_node = h.find("Song")
            d = song_node.get("Dir", "") if song_node is not None else ""
            pack, name = song_parts(d)
            steps_node = h.find("Steps")
            diff = steps_node.get("Difficulty", "?") if steps_node is not None else "?"
            hs = h.find("HighScore")
            dt = txt(hs, "DateTime")
            if not dt:
                continue
            try:
                t = datetime.datetime.strptime(dt, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            total += 1
            day = t.date().isoformat()
            mo  = t.strftime("%Y-%m")
            daily[day] += 1
            monthly[mo] += 1
            if d:
                m_dirs[mo].add(d)
            hour[t.hour] += 1
            dow[t.weekday()] += 1  # 0=Mon
            if first is None or t < first:
                first = t
            if last is None or t > last:
                last = t
            # Skill aggregates for the combo chart
            pct = fnum(txt(hs, "PercentDP"), -1)
            if pct >= 0:
                m_pct_sum[mo] += pct
                m_pct_n[mo]   += 1
            tn = hs.find("TapNoteScores")
            if tn is not None:
                counts = {c.tag: inum(c.text) for c in tn}
                taps = sum(counts.get(k, 0) for k in ("W1","W2","W3","W4","W5","Miss"))
                if taps > 0:
                    m_w1[mo]   += counts.get("W1", 0)
                    m_miss[mo] += counts.get("Miss", 0)
                    m_taps[mo] += taps
            m = meta(d)
            recent.append({
                "_dir": d,
                "dt": dt, "song": m["title"] or name, "artist": m["artist"],
                "pack": pack, "diff": diff,
                "pct": round(fnum(txt(hs, "PercentDP")), 4),
                "grade": txt(hs, "Grade"),
                "score": inum(txt(hs, "Score")),
                "combo": inum(txt(hs, "MaxCombo")),
            })
    recent.sort(key=lambda x: x["dt"], reverse=True)
    recent = [r for r in recent if (r["grade"] or "") not in EXCLUDE_GRADES]
    # Resolve banners only for the trimmed list — keeps conversion cost bounded.
    for r in recent[:150]:
        r["banner"] = banner(r.pop("_dir"))
    for r in recent[150:]:
        r.pop("_dir", None)
    # Build the monthly skill series aligned with playsMonthly months.
    months_sorted = sorted(monthly)
    distinct_m = [(mo, len(m_dirs[mo])) for mo in months_sorted]
    accuracy_m = [(mo, round(100 * m_pct_sum[mo] / m_pct_n[mo], 2) if m_pct_n[mo] else None) for mo in months_sorted]
    w1pct_m    = [(mo, round(100 * m_w1[mo]      / m_taps[mo],  2) if m_taps[mo]  else None) for mo in months_sorted]
    misspct_m  = [(mo, round(100 * m_miss[mo]    / m_taps[mo],  2) if m_taps[mo]  else None) for mo in months_sorted]

    return {
        "recordedPlays": total,
        "firstPlay": first.isoformat(sep=" ") if first else "",
        "lastPlay": last.isoformat(sep=" ") if last else "",
        "playsDaily": sorted(daily.items()),
        "playsMonthly": sorted(monthly.items()),
        "distinctSongsMonthly": distinct_m,
        "accuracyMonthly": accuracy_m,
        "w1PctMonthly": w1pct_m,
        "missPctMonthly": misspct_m,
        "hourOfDay": hour,
        "dayOfWeek": dow,
        "recent": recent[:150],
    }


# --- Banner cache (Cache/Banners) -------------------------------------------
# Each file: 32-byte SurfaceHeader (8 LE uint32: w,h,pitch,Rmask,Gmask,Bmask,Amask,bpp)
# then raw pixel bytes. All song banners in this user's cache are ARGB1555.
# Filename: "<mangled-song-dir>_<original-banner-file>_B.<ext>" — the trailing
# segment before extension is the song dir's mangled form plus the banner file
# stem, joined by '_'.  We index by mangled-dir-prefix.
BANNER_EXT_PATTERN = re.compile(r"\.(png|jpg|jpeg|bmp|gif)$", re.I)


def build_banner_index(banners_dir):
    """Map lowercased mangled-song-dir-prefix -> list of (banner_filename, size_bytes).
       The prefix is 'Songs_<pack>_<song>_' — the song dir with a trailing '_'.
       Multiple banners per song are kept; we pick the largest at lookup time.
    """
    idx = collections.defaultdict(list)
    if not banners_dir or not os.path.isdir(banners_dir):
        return idx
    for fn in os.listdir(banners_dir):
        if not BANNER_EXT_PATTERN.search(fn):
            continue
        # Strip extension, then a trailing "_B" version marker if present.
        stem = BANNER_EXT_PATTERN.sub("", fn)
        if stem.endswith("_B"):
            stem = stem[:-2]
        # stem = "Songs_<pack>_<song>_<orig>"; drop the last underscore-segment.
        i = stem.rfind("_")
        if i < 0:
            continue
        prefix = stem[:i].lower()  # "songs_<pack>_<song>"
        try:
            size = os.path.getsize(os.path.join(banners_dir, fn))
        except OSError:
            size = 0
        idx[prefix].append((fn, size))
    return idx


def decode_argb1555(data, w, h, pitch):
    """Pure-Python decode of ARGB1555 raw pixels -> RGB bytes (w*h*3)."""
    out = bytearray(w * h * 3)
    o = 0
    for y in range(h):
        words = struct.unpack_from(f"<{w}H", data, y * pitch)
        for word in words:
            # 5->8 bit expansion via (n * 527 + 23) >> 6
            out[o]     = ((word >> 10) & 0x1F) * 527 + 23 >> 6
            out[o + 1] = ((word >> 5)  & 0x1F) * 527 + 23 >> 6
            out[o + 2] = (word         & 0x1F) * 527 + 23 >> 6
            o += 3
    return bytes(out)


def convert_banner(src_path, dst_path, max_w=160):
    """Decode a StepMania cache banner -> PNG.  Returns True on success."""
    if Image is None:
        return False
    try:
        with open(src_path, "rb") as f:
            hdr = f.read(32)
            data = f.read()
        w, h, pitch, rm, gm, bm, am, bpp = struct.unpack("<8I", hdr)
    except (struct.error, OSError):
        return False
    if bpp == 16 and rm == 0x7C00 and gm == 0x3E0 and bm == 0x1F:
        try:
            rgb = decode_argb1555(data, w, h, pitch)
            img = Image.frombytes("RGB", (w, h), rgb)
        except Exception:
            return False
    else:
        # Other formats not seen in this user's cache; skip rather than risk garbage.
        return False
    if img.width > max_w:
        img = img.resize((max_w, max(1, img.height * max_w // img.width)), Image.LANCZOS)
    try:
        img.save(dst_path, "PNG", optimize=True)
        return True
    except OSError:
        return False


def make_banner_lookup(cache_banners_dir, out_dir):
    """Return get(song_dir)->'banners/<hash>.png' or '' if no banner found.
       Memoized so each song is converted at most once.
    """
    index = build_banner_index(cache_banners_dir)
    if not index:
        return lambda d: ""
    banners_out = os.path.join(out_dir, "banners")
    os.makedirs(banners_out, exist_ok=True)
    memo = {}
    stats = {"hit": 0, "miss": 0, "decode_fail": 0}

    def get(d):
        if d in memo:
            return memo[d]
        key = cache_filename(d).lower()
        candidates = index.get(key, [])
        if not candidates:
            memo[d] = ""
            stats["miss"] += 1
            return ""
        # Largest file = likely the real banner (not a tiny duplicate)
        best_fn = max(candidates, key=lambda c: c[1])[0]
        h = hashlib.md5(d.encode("utf-8")).hexdigest()[:12]
        out_name = f"{h}.png"
        out_path = os.path.join(banners_out, out_name)
        if not os.path.exists(out_path):
            if not convert_banner(os.path.join(cache_banners_dir, best_fn), out_path):
                memo[d] = ""
                stats["decode_fail"] += 1
                return ""
        memo[d] = f"banners/{out_name}"
        stats["hit"] += 1
        return memo[d]

    get.stats = stats
    return get


def resolve_cache_dir():
    """Locate the Cache/Songs dir (3rd arg, $SM_CACHE, or common spots)."""
    if len(sys.argv) > 3:
        return sys.argv[3]
    if os.environ.get("SM_CACHE"):
        return os.environ["SM_CACHE"]
    for cand in (os.path.join(SAVE_DIR, "..", "Cache", "Songs"),
                 os.path.join(HERE, "..", "cachedata", "Cache", "Songs"),
                 os.path.join(HERE, "..", "cachedata", "Songs"),
                 os.path.join(HERE, "..", "savedata", "Cache", "Songs")):
        if os.path.isdir(cand):
            return cand
    return ""


def resolve_banners_dir(cache_songs_dir):
    """Cache/Banners lives next to Cache/Songs."""
    if os.environ.get("SM_BANNERS"):
        return os.environ["SM_BANNERS"]
    if cache_songs_dir:
        cand = os.path.join(os.path.dirname(cache_songs_dir), "Banners")
        if os.path.isdir(cand):
            return cand
    return ""


def main():
    stats_path = os.path.join(SAVE_DIR, "MachineProfile", "Stats.xml")
    upload_dir = os.path.join(SAVE_DIR, "Upload")
    if not os.path.exists(stats_path):
        sys.exit(f"Stats.xml not found at {stats_path}")

    cfg = load_config()

    cache_dir = resolve_cache_dir()
    if cache_dir and os.path.isdir(cache_dir):
        print(f"Song cache: {cache_dir}")
    else:
        print("Song cache: NONE found — artist/title will be blank. "
              "Copy Cache/Songs and pass it as the 3rd arg or $SM_CACHE.")
        cache_dir = ""
    meta = make_meta_lookup(cache_dir)

    banners_dir = resolve_banners_dir(cache_dir)
    if banners_dir:
        print(f"Banner cache: {banners_dir}")
    else:
        print("Banner cache: NONE — recent plays will use the placeholder.")
    # Re-create the output banners/ each build so removed songs don't linger.
    banners_out = os.path.join(OUT_DIR, "banners")
    if os.path.isdir(banners_out):
        shutil.rmtree(banners_out)
    banner = make_banner_lookup(banners_dir, OUT_DIR)

    print(f"Parsing {stats_path} ...")
    stats = parse_stats(stats_path, meta, banner)
    print(f"  songs with plays: {stats['distinctSongs']}, packs: {len(stats['packs'])}")

    up = {"recordedPlays": 0, "playsDaily": [], "playsMonthly": [],
          "hourOfDay": [0]*24, "dayOfWeek": [0]*7, "recent": [],
          "firstPlay": "", "lastPlay": ""}
    if os.path.isdir(upload_dir):
        print(f"Parsing per-play uploads in {upload_dir} ...")
        up = parse_uploads(upload_dir, meta, banner)
        print(f"  recorded plays: {up['recordedPlays']} "
              f"({up['firstPlay']} -> {up['lastPlay']})")
    if cache_dir:
        s = meta.stats
        tot = s["hit"] + s["miss"]
        print(f"  artist/title matched for {s['hit']}/{tot} songs "
              f"({(100*s['hit']/tot if tot else 0):.0f}%)")
    if banners_dir and hasattr(banner, "stats"):
        b = banner.stats
        tot = b["hit"] + b["miss"] + b["decode_fail"]
        print(f"  banners converted: {b['hit']}/{tot} "
              f"(miss={b['miss']}, decode-fail={b['decode_fail']})")

    # Monthly calories (aggregate the daily series)
    mcal = collections.Counter()
    for day, c in stats["calorieSeries"]:
        if len(day) >= 7:
            mcal[day[:7]] += c
    monthly_cal = sorted((m, round(v, 1)) for m, v in mcal.items())

    data = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "profile": stats["profile"],
        "totals": stats["totals"],
        "distinctSongs": stats["distinctSongs"],
        "recordedPlays": up["recordedPlays"],
        "firstPlay": up["firstPlay"],
        "lastPlay": up["lastPlay"],
        "byDifficulty": stats["byDifficulty"],
        "byGrade": stats["byGrade"],
        "byStyle": stats["byStyle"],
        "gradeMap": GRADE_MAP,
        "diffOrder": DIFF_ORDER,
        "calorieSeries": stats["calorieSeries"],
        "monthlyCalories": monthly_cal,
        "playsDaily": up["playsDaily"],
        "playsMonthly": up["playsMonthly"],
        "distinctSongsMonthly": up.get("distinctSongsMonthly", []),
        "accuracyMonthly": up.get("accuracyMonthly", []),
        "w1PctMonthly": up.get("w1PctMonthly", []),
        "missPctMonthly": up.get("missPctMonthly", []),
        "theme": cfg,
        "hourOfDay": up["hourOfDay"],
        "dayOfWeek": up["dayOfWeek"],
        "recent": up["recent"],
        "songs": stats["songs"],
        "packs": stats["packs"],
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out_json = os.path.join(OUT_DIR, "data.json")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    size = os.path.getsize(out_json)
    print(f"Wrote {out_json} ({size/1024:.0f} KB)")

    # copy the dashboard page (+ placeholder) next to the data
    for asset in ("index.html", "nobanner.svg"):
        src = os.path.join(HERE, asset)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(OUT_DIR, asset))
    print(f"Copied page assets -> {OUT_DIR}")


if __name__ == "__main__":
    main()

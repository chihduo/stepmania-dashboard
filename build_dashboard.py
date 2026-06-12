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
import sys, os, glob, json, collections, datetime, shutil, re, struct, hashlib, subprocess
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
    "playerName": "",  # used in page title/header when non-empty
    "liveDir": "",     # auto-deploy target; set in config.json. Empty = no auto-deploy.
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
    # How many rows to render in the Top Artists / Top Packs cards.
    "topN": {
        "artists": 15,
        "packs": 15,
    },
    "artistAliases": {},
}


# Artist normalization for de-duplication.
# Step 1: lowercase, strip apostrophes/quotes, normalize feat./featuring/ft.
# Step 2: strip everything that's not a "word character" (Python re's \w is
#         Unicode-aware, so CJK/Hangul/etc. survive; only ASCII punctuation,
#         spaces, hyphens, ☆, *, etc. are removed).
# This merges TWICE/Twice, Girls' Generation/Girls Generation, T-ara/T ARA/
# T-Ari, GFRIEND/G-Friend, 4Minute/4 Minute, BLACKPINK/Black Pink/BLack Pink,
# Ryu☆/Ryu*/Ryu in feat. credits, etc.
_APOS_QUOTES = re.compile(r'[‘’‚‛′ʼ\'“”„‟″"]')
_FEAT = re.compile(r'\b(featuring|feat\.?|ft\.?)\b')
_NONWORD = re.compile(r'\W+', re.UNICODE)


def normalize_artist(name):
    """Aggressive Unicode-aware artist key. '' if name is empty."""
    if not name:
        return ""
    s = name.strip().lower()
    s = _APOS_QUOTES.sub('', s)
    s = _FEAT.sub('feat', s)
    s = _NONWORD.sub('', s)
    return s


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


def _parse_chart_blocks(text):
    """Parse #NOTEDATA blocks from an SSC cache file.

    Returns {(stepstype, difficulty): {'meter': int|None, 'radar': {...}}}.
    Multiple charts with the same (stepstype, difficulty) — last one wins
    (rare; only for Edit charts authored side-by-side).

    `#RADARVALUES` has 14 numbers per chart (per player; doubles lists them twice):
    stream, voltage, air, freeze, chaos, notes, tapsAndHolds, jumps, holds,
    mines, hands, rolls, lifts, fakes.  The first 5 are 0–1 normalized
    (chart difficulty profile); the rest are raw counts.
    """
    out = {}
    # Each chart starts with '#NOTEDATA:;'.  First slice (before any #NOTEDATA)
    # is the song-level header — skip it.
    blocks = text.split("#NOTEDATA:;")[1:]
    for blk in blocks:
        st = re.search(r"#STEPSTYPE:([^;]*);", blk)
        df = re.search(r"#DIFFICULTY:([^;]*);", blk)
        if not (st and df):
            continue
        stepstype, difficulty = st.group(1).strip(), df.group(1).strip()
        mt = re.search(r"#METER:([^;]*);", blk)
        meter = inum(mt.group(1)) if mt else None
        radar = {}
        rv = re.search(r"#RADARVALUES:([^;]*);", blk)
        if rv:
            try:
                nums = [float(x) for x in rv.group(1).split(",") if x.strip()]
            except ValueError:
                nums = []
            if len(nums) >= 5:
                radar = {
                    "stream":  round(nums[0], 3),
                    "voltage": round(nums[1], 3),
                    "air":     round(nums[2], 3),
                    "freeze":  round(nums[3], 3),
                    "chaos":   round(nums[4], 3),
                }
                if len(nums) >= 9:
                    radar["notes"] = int(nums[5])
                    radar["jumps"] = int(nums[7])
                    radar["holds"] = int(nums[8])
        out[(stepstype, difficulty)] = {"meter": meter, "radar": radar}
    return out


def make_meta_lookup(cache_songs_dir):
    """Return get(dir)->{'artist','title','charts'}, memoized.

    'charts' maps (stepstype, difficulty) -> {'meter', 'radar'} extracted from
    the SSC cache.  Lookup is case-insensitive: recorded song dirs sometimes
    differ in case from the on-disk cache filename (e.g. 'DDR K-POP' vs
    'DDR K-Pop'), and Linux is case-sensitive while the original Windows
    filesystem was not.
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
        meta = {"artist": "", "title": "", "charts": {}, "banner_file": ""}
        if index:
            fn = index.get(cache_filename(d).lower())
            if fn:
                text = open(os.path.join(cache_songs_dir, fn), "rb").read().decode("utf-8", errors="replace")
                meta["artist"] = tag(text, "ARTIST") or tag(text, "ARTISTTRANSLIT")
                meta["title"] = tag(text, "TITLE") or tag(text, "TITLETRANSLIT")
                meta["banner_file"] = tag(text, "BANNER")
                meta["charts"] = _parse_chart_blocks(text)
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
def aggregate_artists(songs, aliases):
    """Group songs by normalized artist; return top list sorted by plays.

    `aliases` maps canonical-display-name -> [list of variant strings to
    force into the same group]. Normalization is applied to both sides.
    `songs` is the list of song dicts emitted by parse_stats (each has
    'artist' and 'plays').

    Returns: [{artist, plays, songs, variants}] sorted by plays desc.
    """
    # Build alias lookup: normalized variant -> (canonical_norm, canonical_display)
    # Stored as a tuple so we can both redirect the bucket key (so variants merge
    # into one group) AND remember the display name (so the canonical wins over
    # the most-played raw variant).
    alias_lookup = {}
    for canonical, variants in (aliases or {}).items():
        if not canonical or canonical.startswith("_"):
            continue  # skip _comment etc.
        canonical_norm = normalize_artist(canonical)
        if not canonical_norm:
            continue
        for v in [canonical] + list(variants or []):
            k = normalize_artist(v)
            if k:
                alias_lookup[k] = (canonical_norm, canonical)

    # Bucket by normalized key (or aliased canonical key)
    buckets = {}  # key -> {display, plays, songs, variants{raw:plays}}
    for s in songs:
        raw = (s.get("artist") or "").strip()
        if not raw:
            continue
        raw_key = normalize_artist(raw)
        if not raw_key:
            continue
        if raw_key in alias_lookup:
            bucket_key, canonical_display = alias_lookup[raw_key]
        else:
            bucket_key, canonical_display = raw_key, None
        b = buckets.setdefault(bucket_key, {
            "display": canonical_display,
            "plays": 0, "songs": 0, "variants": collections.Counter(),
        })
        # If this song's variant supplies a canonical display and an earlier
        # song in the same bucket didn't, set it now.
        if canonical_display and not b["display"]:
            b["display"] = canonical_display
        b["plays"] += s["plays"]
        b["songs"] += 1
        b["variants"][raw] += s["plays"]

    # Pick display name: alias override wins; else the most-played variant
    out = []
    for b in buckets.values():
        display = b["display"] or b["variants"].most_common(1)[0][0]
        out.append({
            "artist": display, "plays": b["plays"], "songs": b["songs"],
            "variants": len(b["variants"]),
        })
    out.sort(key=lambda x: -x["plays"])
    return out


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

    # SongScores -> per song aggregate (and per-chart score detail for the modal)
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
            m = meta(d)
            plays = 0
            last = ""
            best_pct = None
            best_grade = None
            diffs = {}
            charts = []  # per-chart detail for the modal
            for st in s.findall("Steps"):
                diff = st.get("Difficulty", "?")
                stepstype = st.get("StepsType", "")
                hsl = st.find("HighScoreList")
                n = inum(txt(hsl, "NumTimesPlayed"))
                plays += n
                diffs[diff] = diffs.get(diff, 0) + n
                lp = txt(hsl, "LastPlayed")
                if lp > last:
                    last = lp
                # Per-score detail for the modal — compact field names since this
                # array can run thousands of entries across all songs.
                chart_scores = []
                for hs in (hsl.findall("HighScore") if hsl is not None else []):
                    pct = fnum(txt(hs, "PercentDP"), -1)
                    if pct >= 0 and (best_pct is None or pct > best_pct):
                        best_pct = pct
                        best_grade = txt(hs, "Grade")
                    tn = hs.find("TapNoteScores")
                    hn = hs.find("HoldNoteScores")
                    so = {
                        "dt":    txt(hs, "DateTime"),
                        "pct":   round(fnum(txt(hs, "PercentDP")), 4),
                        "grade": txt(hs, "Grade"),
                        "sc":    inum(txt(hs, "Score")),
                        "co":    inum(txt(hs, "MaxCombo")),
                        "sv":    round(fnum(txt(hs, "SurviveSeconds")), 1),
                    }
                    if tn is not None:
                        so["j"] = [
                            inum(txt(tn, "W1")), inum(txt(tn, "W2")),
                            inum(txt(tn, "W3")), inum(txt(tn, "W4")),
                            inum(txt(tn, "W5")), inum(txt(tn, "Miss")),
                        ]
                    if hn is not None:
                        so["h"] = [
                            inum(txt(hn, "Held")), inum(txt(hn, "LetGo")),
                            inum(txt(hn, "MissedHold")),
                        ]
                    mods = txt(hs, "Modifiers")
                    # Skip the user's near-universal default to keep JSON small.
                    if mods and mods != "Overhead":
                        so["m"] = mods
                    chart_scores.append(so)
                chart_scores.sort(key=lambda x: x["dt"], reverse=True)
                cm = m["charts"].get((stepstype, diff), {})
                charts.append({
                    "diff": diff,
                    "stepstype": stepstype,
                    "meter": cm.get("meter"),
                    "radar": cm.get("radar") or {},
                    "plays": n,
                    "lastPlayed": lp,
                    "scores": chart_scores,
                })
            if plays <= 0:
                continue
            # Sort charts by difficulty order; unknown diffs go last.
            charts.sort(key=lambda c: (DIFF_ORDER.index(c["diff"])
                                       if c["diff"] in DIFF_ORDER else 99))
            songs.append({
                "song": m["title"] or name, "artist": m["artist"], "pack": pack,
                "dir": d, "plays": plays,
                "banner": banner(d),
                "last": last,
                "bestPct": round(best_pct, 4) if best_pct is not None else None,
                "bestGrade": best_grade or "",
                "diffs": diffs,
                "charts": charts,
            })
            pack_plays[pack] += plays
            pack_songs[pack] += 1

    songs.sort(key=lambda x: (-x["plays"], x["song"].lower()))
    # Packs are computed from all songs above; the D/F filter for the ranking
    # table now happens client-side so modal lookups by song dir still work.
    packs = [{"pack": p, "plays": pack_plays[p], "songs": pack_songs[p]}
             for p in pack_plays]
    packs.sort(key=lambda x: -x["plays"])
    all_song_count = len(songs)

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
    # Per-month play counts bucketed by difficulty. The dashboard renders these
    # as the colored segments of each month's Plays bar. Edit and any unknown /
    # missing difficulty silently merge into Medium so the visible palette stays
    # to the five "normal" tiers.
    DIFF_BUCKETS = ("Beginner", "Easy", "Medium", "Hard", "Challenge")
    BUCKET_FOR = {d: d for d in DIFF_BUCKETS}
    m_by_diff = collections.defaultdict(lambda: collections.Counter())
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
            m_by_diff[mo][BUCKET_FOR.get(diff, "Medium")] += 1
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
    # 'dir' is kept on each row so the modal click handler can find the
    # matching song record in DATA.songs.
    for r in recent[:150]:
        r["dir"] = r["_dir"]
        r["banner"] = banner(r.pop("_dir"))
    for r in recent[150:]:
        r.pop("_dir", None)
    # Build the monthly skill series aligned with playsMonthly months.
    months_sorted = sorted(monthly)
    distinct_m = [(mo, len(m_dirs[mo])) for mo in months_sorted]
    plays_by_diff_m = [(mo, {b: m_by_diff[mo][b] for b in DIFF_BUCKETS}) for mo in months_sorted]
    accuracy_m = [(mo, round(100 * m_pct_sum[mo] / m_pct_n[mo], 2) if m_pct_n[mo] else None) for mo in months_sorted]
    w1pct_m    = [(mo, round(100 * m_w1[mo]      / m_taps[mo],  2) if m_taps[mo]  else None) for mo in months_sorted]
    misspct_m  = [(mo, round(100 * m_miss[mo]    / m_taps[mo],  2) if m_taps[mo]  else None) for mo in months_sorted]

    return {
        "recordedPlays": total,
        "firstPlay": first.isoformat(sep=" ") if first else "",
        "lastPlay": last.isoformat(sep=" ") if last else "",
        "playsDaily": sorted(daily.items()),
        "playsMonthly": sorted(monthly.items()),
        "playsMonthlyByDifficulty": plays_by_diff_m,
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
# Some packs use a looping video as the banner (#BANNER:foo.avi;). StepMania
# does NOT pre-render those into Cache/Banners, so the source videos must be
# staged separately (see wsl/collect-video-banners.sh) and we grab one frame.
VIDEO_EXT_PATTERN = re.compile(r"\.(avi|mp4|mpg|mpeg|mkv|wmv|flv|webm)$", re.I)


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


def convert_image_banner(src_path, dst_path, max_w=160):
    """Copy/normalize a plain image (e.g. a frame pre-extracted in WSL by
    collect-video-banners.sh) -> PNG. Returns True on success."""
    if Image is None:
        return False
    try:
        img = Image.open(src_path).convert("RGB")
    except Exception:
        return False
    if img.width > max_w:
        img = img.resize((max_w, max(1, img.height * max_w // img.width)), Image.LANCZOS)
    try:
        img.save(dst_path, "PNG", optimize=True)
        return True
    except OSError:
        return False


FFMPEG = shutil.which("ffmpeg")


def convert_video_banner(src_path, dst_path, max_w=160):
    """Grab one frame from a video banner -> PNG. Returns True on success.

    Seeks to 1s first (frame 0 of looping banner videos is often black),
    falling back to the very first frame for clips shorter than that.
    """
    if not FFMPEG:
        return False
    for seek in ("1", "0"):
        try:
            r = subprocess.run(
                [FFMPEG, "-y", "-loglevel", "error", "-ss", seek, "-i", src_path,
                 "-frames:v", "1", "-vf", f"scale='min({max_w},iw)':-1", dst_path],
                capture_output=True, timeout=30)
            if r.returncode == 0 and os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
                return True
        except (subprocess.TimeoutExpired, OSError):
            return False
    return False


def make_banner_lookup(cache_banners_dir, out_dir, meta=None, persist_dir=None,
                       video_dir=None):
    """Return get(song_dir)->'banners/<hash>.png' or '' if no banner found.
       Memoized so each song is converted at most once.

       Lookup strategies, in order:
         1) Exact: if the song's cache file recorded its banner filename
            (#BANNER:foo.png) we know the cache banner is named
            "<mangled-song-dir>_<banner-file>" — look it up case-insensitively.
         2) Video: if #BANNER names a video (StepMania never pre-renders those
            into Cache/Banners), look in `video_dir` (default: video-banners/
            next to this script, override with $SM_VIDEO_BANNERS; populate with
            wsl/collect-video-banners.sh). A pre-extracted frame
            ("<name>.<video-ext>.png", made in WSL — only KBs to transfer) is
            preferred; a staged raw video also works (frame extracted here
            with ffmpeg).
         3) Prefix scan: legacy fallback for songs whose cache lacks a #BANNER
            tag or whose banner stem contains no underscores. Works whenever
            rfind('_') correctly splits dir from stem.

       Conversions are cached in `persist_dir` (default: .banner-cache/ next to
       this script, override with $SM_BANNER_CACHE) so each banner is decoded
       once ever, not once per build: public/banners/ is wiped every build, but
       repopulating it from the cache is a plain file copy. Cache entries are
       keyed by song dir + source name + mtime + size, so a touched source
       re-converts automatically and the stale entry is simply never read again.
    """
    if not cache_banners_dir or not os.path.isdir(cache_banners_dir):
        return lambda d: ""
    exact_index = {}        # lowercased filename -> actual filename
    for fn in os.listdir(cache_banners_dir):
        if BANNER_EXT_PATTERN.search(fn):
            exact_index[fn.lower()] = fn
    prefix_index = build_banner_index(cache_banners_dir)
    if video_dir is None:
        video_dir = os.environ.get("SM_VIDEO_BANNERS") or os.path.join(HERE, "video-banners")
    # lowercased "<mangled-dir>_<banner-file>[.png]" -> actual filename.
    # Holds both raw staged videos and pre-extracted .png frames.
    video_index = {}
    if os.path.isdir(video_dir):
        for fn in os.listdir(video_dir):
            video_index[fn.lower()] = fn
    if not exact_index and not prefix_index and not video_index:
        return lambda d: ""
    banners_out = os.path.join(out_dir, "banners")
    os.makedirs(banners_out, exist_ok=True)
    if persist_dir is None:
        persist_dir = os.environ.get("SM_BANNER_CACHE") or os.path.join(HERE, ".banner-cache")
    try:
        os.makedirs(persist_dir, exist_ok=True)
        persist_ok = os.access(persist_dir, os.W_OK)
    except OSError:
        persist_ok = False  # read-only checkout etc. — fall back to converting each build
    memo = {}
    stats = {"hit": 0, "miss": 0, "decode_fail": 0, "cached": 0}

    def find_source(d):
        """Return (full_source_path, converter) or (None, None)."""
        if meta is not None:
            banner_file = (meta(d) or {}).get("banner_file") or ""
            if banner_file:
                expected = f"{cache_filename(d)}_{banner_file}".lower()
                actual = exact_index.get(expected)
                if actual:
                    return os.path.join(cache_banners_dir, actual), convert_banner
                if VIDEO_EXT_PATTERN.search(banner_file):
                    # Pre-extracted frame (preferred — no ffmpeg needed here)
                    pre = video_index.get(expected + ".png")
                    if pre:
                        return os.path.join(video_dir, pre), convert_image_banner
                    actual = video_index.get(expected)
                    if actual:
                        return os.path.join(video_dir, actual), convert_video_banner
        candidates = prefix_index.get(cache_filename(d).lower(), [])
        if candidates:
            best = max(candidates, key=lambda c: c[1])[0]
            return os.path.join(cache_banners_dir, best), convert_banner
        return None, None

    def get(d):
        if d in memo:
            return memo[d]
        src_path, converter = find_source(d)
        if not src_path:
            memo[d] = ""
            stats["miss"] += 1
            return ""
        h = hashlib.md5(d.encode("utf-8")).hexdigest()[:12]
        out_name = f"{h}.png"
        out_path = os.path.join(banners_out, out_name)
        if not os.path.exists(out_path):
            cached_path = None
            if persist_ok:
                try:
                    st = os.stat(src_path)
                    ck = hashlib.md5(f"{d}|{os.path.basename(src_path)}|{st.st_mtime_ns}|{st.st_size}"
                                     .encode("utf-8")).hexdigest()[:16]
                    cached_path = os.path.join(persist_dir, f"{ck}.png")
                except OSError:
                    pass
            if cached_path and os.path.exists(cached_path):
                shutil.copy2(cached_path, out_path)
                stats["cached"] += 1
            else:
                if not converter(src_path, out_path):
                    memo[d] = ""
                    stats["decode_fail"] += 1
                    return ""
                if cached_path:
                    shutil.copy2(out_path, cached_path)
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
    banner = make_banner_lookup(banners_dir, OUT_DIR, meta=meta)

    print(f"Parsing {stats_path} ...")
    stats = parse_stats(stats_path, meta, banner)
    print(f"  songs with plays: {stats['distinctSongs']}, packs: {len(stats['packs'])}")

    # Build the artist top-list with normalization + manual aliases.
    # The unfiltered song list (before D/F drop) is what we want, since the
    # D/F filter is for the *ranking table*, not for artist counts.
    artists = aggregate_artists(stats["songs"], cfg.get("artistAliases", {}))
    if artists:
        raw_n = sum(1 for s in stats["songs"] if (s.get("artist") or "").strip())
        print(f"  artists: {len(artists)} groups (from {raw_n} raw names, "
              f"top: {artists[0]['artist']!r} = {artists[0]['plays']} plays "
              f"across {artists[0]['variants']} variants)")

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
        print(f"  banners resolved: {b['hit']}/{tot} "
              f"({b['cached']} from cache, {b['hit']-b['cached']} converted, "
              f"miss={b['miss']}, decode-fail={b['decode_fail']})")

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
        "playsMonthlyByDifficulty": up.get("playsMonthlyByDifficulty", []),
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
        "artists": artists,
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

    # Auto-deploy to the live web root if it's writable by this user.
    # Skipped silently otherwise — fall back to running deploy.sh with sudo.
    live = cfg.get("liveDir") or ""
    if live and os.path.isdir(live) and os.access(live, os.W_OK):
        live_banners = os.path.join(live, "banners")
        if os.path.isdir(live_banners):
            shutil.rmtree(live_banners)
        for entry in os.listdir(OUT_DIR):
            src = os.path.join(OUT_DIR, entry)
            dst = os.path.join(live, entry)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
        print(f"Auto-deployed to {live}")
    elif live and os.path.isdir(live):
        print(f"NOTE: {live} exists but is not writable; run deploy.sh with sudo "
              "(or one-time: sudo chown -R $USER:www-data {0} && sudo chmod -R g+w {0} "
              "&& sudo chmod g+s {0})".format(live))


if __name__ == "__main__":
    main()

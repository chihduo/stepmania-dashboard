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
  defaults: SAVE_DIR=../savedata/Save, OUT_DIR=./public
"""
import sys, os, glob, json, collections, datetime, shutil, re
import xml.etree.ElementTree as ET

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


# --------------------------------------------------------------------------
# 1) Stats.xml : GeneralData aggregates + SongScores (authoritative play counts)
# --------------------------------------------------------------------------
def parse_stats(stats_path):
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
            songs.append({
                "song": name, "pack": pack, "dir": d, "plays": plays,
                "last": last,
                "bestPct": round(best_pct, 4) if best_pct is not None else None,
                "bestGrade": best_grade or "",
                "diffs": diffs,
            })
            pack_plays[pack] += plays
            pack_songs[pack] += 1

    songs.sort(key=lambda x: (-x["plays"], x["song"].lower()))
    packs = [{"pack": p, "plays": pack_plays[p], "songs": pack_songs[p]}
             for p in pack_plays]
    packs.sort(key=lambda x: -x["plays"])

    return {
        "profile": profile, "totals": totals,
        "byDifficulty": by_difficulty, "byGrade": by_grade, "byStyle": by_style,
        "calorieSeries": cal, "songs": songs, "packs": packs,
        "distinctSongs": len(songs),
    }


# --------------------------------------------------------------------------
# 2) Upload/*.xml : per-play event log (exact timestamps)
# --------------------------------------------------------------------------
def parse_uploads(upload_dir):
    files = sorted(glob.glob(os.path.join(upload_dir, "*.xml")))
    daily = collections.Counter()
    monthly = collections.Counter()
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
            daily[day] += 1
            monthly[t.strftime("%Y-%m")] += 1
            hour[t.hour] += 1
            dow[t.weekday()] += 1  # 0=Mon
            if first is None or t < first:
                first = t
            if last is None or t > last:
                last = t
            recent.append({
                "dt": dt, "song": name, "pack": pack, "diff": diff,
                "pct": round(fnum(txt(hs, "PercentDP")), 4),
                "grade": txt(hs, "Grade"),
                "score": inum(txt(hs, "Score")),
                "combo": inum(txt(hs, "MaxCombo")),
            })
    recent.sort(key=lambda x: x["dt"], reverse=True)
    return {
        "recordedPlays": total,
        "firstPlay": first.isoformat(sep=" ") if first else "",
        "lastPlay": last.isoformat(sep=" ") if last else "",
        "playsDaily": sorted(daily.items()),
        "playsMonthly": sorted(monthly.items()),
        "hourOfDay": hour,
        "dayOfWeek": dow,
        "recent": recent[:150],
    }


def main():
    stats_path = os.path.join(SAVE_DIR, "MachineProfile", "Stats.xml")
    upload_dir = os.path.join(SAVE_DIR, "Upload")
    if not os.path.exists(stats_path):
        sys.exit(f"Stats.xml not found at {stats_path}")

    print(f"Parsing {stats_path} ...")
    stats = parse_stats(stats_path)
    print(f"  songs with plays: {stats['distinctSongs']}, packs: {len(stats['packs'])}")

    up = {"recordedPlays": 0, "playsDaily": [], "playsMonthly": [],
          "hourOfDay": [0]*24, "dayOfWeek": [0]*7, "recent": [],
          "firstPlay": "", "lastPlay": ""}
    if os.path.isdir(upload_dir):
        print(f"Parsing per-play uploads in {upload_dir} ...")
        up = parse_uploads(upload_dir)
        print(f"  recorded plays: {up['recordedPlays']} "
              f"({up['firstPlay']} -> {up['lastPlay']})")

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

    # copy the dashboard page next to the data
    src_html = os.path.join(HERE, "index.html")
    if os.path.exists(src_html):
        shutil.copy(src_html, os.path.join(OUT_DIR, "index.html"))
        print(f"Copied index.html -> {OUT_DIR}")


if __name__ == "__main__":
    main()

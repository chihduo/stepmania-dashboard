#!/usr/bin/env python3
"""Validate a native StepMania export, then use the existing dashboard builder.

The data checkout is never imported or executed. Only the documented XML,
metadata JSON and PNG files are read. No liveDir deployment is used here.
"""
import argparse
import base64
import collections
import copy
import io
import hashlib
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

import build_dashboard as builder

PROFILE = re.compile(r"[A-Za-z0-9-]{8,64}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
GENERAL = set("DisplayName Guid IsMachine LastPlayedDate TotalSessions TotalSessionSeconds TotalGameplaySeconds TotalCaloriesBurned TotalDancePoints NumTotalSongsPlayed TotalTapsAndHolds TotalJumps TotalHolds TotalRolls TotalMines TotalHands TotalLifts".split())
SCORE = set("Guid StageGuid PlayerGuid Grade Score PercentDP SurviveSeconds MaxCombo Modifiers DateTime".split())
JUDGMENTS = set("W1 W2 W3 W4 W5 Miss HitMine AvoidMine CheckpointHit CheckpointMiss Held LetGo MissedHold".split())
DIFFICULTIES = set("Beginner Easy Medium Hard Challenge Edit".split())
GRADES = {f"Tier{i:02d}" for i in range(1,21)} | {"Failed", "NoData"}
CHILDREN = {
    "Stats": {"GeneralData", "SongScores", "CalorieData", "RecentSongScores"},
    "GeneralData": GENERAL | {"NumSongsPlayedByDifficulty", "NumStagesPassedByGrade", "NumSongsPlayedByStyle"},
    "NumSongsPlayedByDifficulty": DIFFICULTIES,
    "NumStagesPassedByGrade": GRADES,
    "NumSongsPlayedByStyle": {"Style"},
    "SongScores": {"Song"}, "Song": {"Steps"}, "Steps": {"HighScoreList"},
    "HighScoreList": {"NumTimesPlayed", "LastPlayed", "HighScore"},
    "HighScore": SCORE | {"TapNoteScores", "HoldNoteScores"},
    "TapNoteScores": JUDGMENTS, "HoldNoteScores": JUDGMENTS,
    "CalorieData": {"CaloriesBurned"},
    "RecentSongScores": {"HighScoreForASongAndSteps"},
    "HighScoreForASongAndSteps": {"Song", "Steps", "HighScore"},
}
ATTRS = {"Song": {"Dir"}, "Steps": {"StepsType", "Difficulty", "Description", "Hash"},
         "Style": {"Game", "Style"}, "CaloriesBurned": {"Date"}}


def read_bytes(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular file: {path.name}")
    if path.stat().st_size > limit:
        raise ValueError(f"File too large: {path.name}")
    return path.read_bytes()


def read_json(path, limit=256*1024):
    return json.loads(read_bytes(path, limit))


def xml(path, limit, *, allow_theme_songs=False):
    raw = read_bytes(path, limit)
    if b"<!" in raw:
        raise ValueError("XML declarations/entities/comments are not allowed")
    root = ET.fromstring(raw)
    if root.tag != "Stats":
        raise ValueError("Expected Stats XML root")
    for node in root.iter():
        if set(node.attrib) - ATTRS.get(node.tag, set()):
            raise ValueError(f"Unexpected XML attributes: {node.tag}")
        if any(c.tag not in CHILDREN.get(node.tag, set()) for c in node):
            raise ValueError(f"Unexpected XML fields: {node.tag}")
        if len(node.text or "") > 8192:
            raise ValueError("XML value too long")
        if node.tag == "Song":
            validate_song_dir(node.get("Dir", ""), allow_theme=allow_theme_songs)
    return root


def validate_song_dir(d, *, allow_theme=False):
    if not isinstance(d, str) or len(d) > 2048 or "\\" in d or any(ord(c) < 32 for c in d):
        raise ValueError("Invalid relative song directory")
    parts = (d[:-1] if d.endswith("/") else d).split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("Invalid relative song directory")
    if parts[0] in ("Songs", "AdditionalSongs") and len(parts) > 1:
        return
    # Calibration songs live in Themes/<theme>/Other/ and can remain in old
    # cumulative profiles. The builder already excludes them from song lists.
    # Only Stats.xml may contain these entries; metadata and events stay strict.
    if allow_theme and len(parts) >= 3 and parts[0] == "Themes" and parts[2] == "Other":
        return
    raise ValueError("Invalid relative song directory")


def event_identity(node):
    hs = node.find("HighScore")
    guid = builder.txt(hs, "Guid")
    if not guid:
        raise ValueError("Exported play is missing its persistent Guid")
    # Exporter preserves original GUIDs and assigns deterministic legacy IDs.
    return hashlib.sha256(guid.encode()).hexdigest()


def verify_log_history(previous, current):
    """Reject a wrong/reset profile or incomplete per-play history."""
    if previous.get("profile", {}).get("guid") != current["profile"]["guid"]:
        raise ValueError("Profile differs from published history; select the matching local profile")
    for key in ("songsPlayed", "tapsAndHolds", "jumps", "holds", "rolls", "mines", "hands", "lifts", "dancePoints", "gameplaySeconds", "sessions"):
        if current["totals"].get(key, 0) < previous.get("totals", {}).get(key, 0):
            raise ValueError(f"Historical total decreased: {key}; restore the complete Save history")
    # Missing logs also reduce some merged per-song counts. Diagnose the log
    # gap first so users can distinguish omitted/filtered logs from a reset save.
    advice = ("Check the complete Save/Upload history and skipped_other_profiles "
              "in Save/Dashboard/pending.json; older logs without a matching "
              "PlayerGuid are filtered out by local-profile uploads. "
              "The published dashboard has not been replaced.")
    uploaded = current.get("recordedPlays", 0)
    published = previous.get("recordedPlays", 0)
    if uploaded < published:
        raise ValueError(f"Historical play logs are incomplete: {uploaded} uploaded, "
                         f"{published} already published. {advice}")
    for key in ("playsDaily", "playsMonthly"):
        counts = dict(current.get(key, []))
        for day, n in previous.get(key, []):
            if counts.get(day, 0) < n:
                raise ValueError(f"Historical play logs are incomplete for {day}: "
                                 f"{counts.get(day, 0)} uploaded, {n} already published. {advice}")


def verify_history(previous, current):
    """Reject a reset/wrong profile or a lossy replacement of a published site."""
    verify_log_history(previous, current)
    songs = {s["dir"]: s for s in current["songs"]}
    for old in previous.get("songs", []):
        new = songs.get(old["dir"])
        if not new or new["plays"] < old["plays"]:
            count = new["plays"] if new else "missing"
            raise ValueError(f"Historical song plays are missing for {old['dir']}: "
                             f"{count} uploaded, {old['plays']} published; "
                             "restore the complete profile and Save/Upload")


def verify_published_events(previous, events):
    """A retained dashboard score must not hide a missing or altered upload event."""
    for song in previous.get("songs", []):
        for chart in song.get("charts", []):
            key = (song["dir"], chart["stepstype"], chart["diff"])
            for score in chart.get("scores", []):
                guid = score.get("id")
                if not guid:
                    continue
                event = events.get(guid)
                if event is None:
                    raise ValueError(f"Historical play event is missing: {guid} ({song['dir']}); "
                                     "restore the complete Save/Upload history")
                if event[:3] != key or builder.score_fingerprint(event[3]) != builder.score_fingerprint(score):
                    raise ValueError(f"Historical play event changed: {guid} ({song['dir']})")


def merge_preserved_scores(scores, published):
    """Union score histories, matching legacy records once and keeping distinct IDs."""
    ids = {s["id"]: i for i, s in enumerate(scores) if s.get("id")}
    all_scores = collections.defaultdict(collections.deque)
    legacy_scores = collections.defaultdict(collections.deque)
    for i, score in enumerate(scores):
        key = builder.score_fingerprint(score)
        all_scores[key].append(i)
        if not score.get("id"):
            legacy_scores[key].append(i)
    matched = set()
    added = 0
    # Reserve exact event identities before matching indistinguishable legacy
    # scores, so a legacy score cannot consume another play's known ID.
    for score in sorted(published, key=lambda score: not bool(score.get("id"))):
        guid = score.get("id")
        key = builder.score_fingerprint(score)
        if guid and guid in ids:
            i = ids[guid]
            if builder.score_fingerprint(scores[i]) != key:
                raise ValueError(f"Historical score changed for event {guid}")
            matched.add(i)
            continue
        candidates = (legacy_scores if guid else all_scores)[key]
        while candidates and candidates[0] in matched:
            candidates.popleft()
        if candidates:
            i = candidates.popleft()
            matched.add(i)
            if guid:
                scores[i]["id"] = guid
                ids[guid] = i
            continue
        scores.append(copy.deepcopy(score))
        if guid:
            ids[guid] = len(scores) - 1
        added += 1
    scores.sort(key=lambda score: score.get("dt", ""), reverse=True)
    return added


def preserve_published_history(previous, current):
    """Keep known counters and profile-only scores after validating the new logs.

    A live export can include started attempts that the saved local profile later
    forgets. Stats.xml also trims its retained high scores. Neither should erase
    history already published; missing uploads and reset profiles still fail.
    """
    verify_log_history(previous, current)
    songs = {song["dir"]: song for song in current["songs"]}
    report = {"chart_counters": [], "score_records": 0}
    for old in previous.get("songs", []):
        song = songs.get(old["dir"])
        if song is None:
            raise ValueError(f"Historical song is missing from the profile: {old['dir']}")
        old_groups = collections.defaultdict(list)
        new_groups = collections.defaultdict(list)
        for chart in old.get("charts", []):
            old_groups[(chart["stepstype"], chart["diff"])].append(chart)
        for chart in song.get("charts", []):
            new_groups[(chart["stepstype"], chart["diff"])].append(chart)
        for key, old_charts in old_groups.items():
            charts = new_groups.get(key, [])
            if not charts:
                raise ValueError(f"Historical chart is missing from the profile: {old['dir']} {key}")
            if len(charts) != 1 or len(old_charts) != 1:
                # Older JSON does not distinguish multiple Edit charts. Accept
                # intact histories, but do not guess which chart needs recovery.
                before = collections.Counter(builder.score_fingerprint(s) for c in old_charts for s in c["scores"])
                after = collections.Counter(builder.score_fingerprint(s) for c in charts for s in c["scores"])
                if (len(charts) < len(old_charts) or before - after or
                        sum(c["plays"] for c in charts) < sum(c["plays"] for c in old_charts)):
                    raise ValueError(f"Cannot safely recover ambiguous historical charts: {old['dir']} {key}")
                continue
            old_chart, chart = old_charts[0], charts[0]
            if chart.get("meter") is None:
                chart["meter"] = builder.chart_meter(old_chart.get("meter"))
            report["score_records"] += merge_preserved_scores(chart["scores"], old_chart["scores"])
            count = max(chart["plays"], old_chart["plays"], len(chart["scores"]))
            if count > chart["plays"]:
                report["chart_counters"].append({"dir": song["dir"], "stepstype": key[0],
                                                 "diff": key[1], "uploaded": chart["plays"], "retained": count})
            chart["plays"] = count
            chart["lastPlayed"] = max(chart.get("lastPlayed") or "", old_chart.get("lastPlayed") or "",
                                      max((score.get("dt", "")[:10] for score in chart["scores"]), default=""))
        song["plays"] = max(song["plays"], old["plays"], sum(c["plays"] for c in song["charts"]))
        song["last"] = max(song.get("last") or "", old.get("last") or "",
                           max((c.get("lastPlayed") or "" for c in song["charts"]), default=""))
        song["diffs"] = {}
        for chart in song["charts"]:
            song["diffs"][chart["diff"]] = song["diffs"].get(chart["diff"], 0) + chart["plays"]
        best = max((s for c in song["charts"] for s in c["scores"]), key=lambda s: s["pct"], default=None)
        if best and (song.get("bestPct") is None or best["pct"] > song["bestPct"]):
            song["bestPct"], song["bestGrade"] = best["pct"], best["grade"]
    current["songs"].sort(key=lambda song: (-song["plays"], song["song"].lower()))
    # Rankings and breakdown totals must use the same retained song counts.
    packs = {}
    for song in current["songs"]:
        pack = packs.setdefault(song["pack"], {"pack": song["pack"], "plays": 0, "songs": 0})
        pack["plays"] += song["plays"]
        pack["songs"] += 1
    current["packs"] = sorted(packs.values(), key=lambda pack: -pack["plays"])
    current["artists"] = builder.aggregate_artists(current["songs"], current.get("theme", {}).get("artistAliases", {}))
    return report


def build(data_dir, profile, output, baseline=None, revision="local"):
    data_dir, output = Path(data_dir), Path(output)
    if not PROFILE.fullmatch(profile):
        raise ValueError("Invalid profile identifier")
    # Reject symlinks anywhere, including a symlinked parent of an allowed file.
    if data_dir.is_symlink() or any(p.is_symlink() for p in data_dir.rglob("*")):
        raise ValueError("Symlinks are not allowed in an export")
    pdir = data_dir / "profiles" / profile
    manifest = read_json(pdir / "manifest.json")
    if manifest.get("version") != 1 or manifest.get("profile_guid") != profile or manifest.get("profile_kind") not in ("local", "machine"):
        raise ValueError("Unsupported export version or wrong profile")
    stats = xml(pdir / "Stats.xml", 32*1024*1024, allow_theme_songs=True)
    if stats.find("RecentSongScores") is not None or stats.findtext("GeneralData/Guid") != profile:
        raise ValueError("Invalid profile snapshot")
    previous = read_json(Path(baseline)/"data.json", 64*1024*1024) if baseline else None
    previous_songs = {s["dir"]: s for s in (previous or {}).get("songs", [])}
    metadata = {}
    for path in sorted((pdir / "songs").glob("*.json")):
        m = read_json(path)
        validate_song_dir(m["dir"])
        if path.stem != hashlib.sha256(m["dir"].encode()).hexdigest():
            raise ValueError("Song metadata filename does not match its directory")
        if set(m) - {"dir", "title", "artist", "charts", "banner"}:
            raise ValueError("Unexpected song metadata")
        if not all(isinstance(m.get(k, ""), str) and len(m.get(k, "")) <= 2048 for k in ("title", "artist", "banner")):
            raise ValueError("Invalid song text")
        charts = {}
        for c in m.get("charts", []):
            if not isinstance(c, dict) or set(c) - {"stepstype", "diff", "meter", "radar"}:
                raise ValueError(f"Invalid chart metadata for {m['dir']!r}")
            if type(c.get("meter")) is not int:
                raise ValueError(f"Expected an integer chart meter for {m['dir']!r} "
                                 f"({c.get('stepstype')!r}, {c.get('diff')!r})")
            if not isinstance(c.get("radar", {}), dict) or any(not isinstance(v, (int,float)) or not 0 <= v <= 10000000 for v in c.get("radar", {}).values()):
                raise ValueError("Invalid chart radar")
            charts[(c["stepstype"], c["diff"])] = {"meter": c["meter"], "radar": c.get("radar", {})}
        m["charts"] = charts
        metadata[m["dir"]] = m

    def meta(d):
        m = metadata.get(d)
        if m:
            return m
        old = previous_songs.get(d, {})
        return {"title": old.get("song", ""), "artist": old.get("artist", ""),
                "charts": {(c["stepstype"],c["diff"]): c for c in old.get("charts", [])}}

    # Pack images have their own exact virtual directory, independent of a
    # song's metadata. Older uploaders simply supply no pack records.
    packs = {}
    for path in sorted((pdir / "packs").glob("*.json")):
        record = read_json(path)
        if not isinstance(record, dict) or set(record) != {"dir", "banner"}:
            raise ValueError("Invalid pack artwork record")
        directory = record["dir"]
        validate_song_dir(directory)
        if directory.count("/") != 2 or not directory.endswith("/") or path.stem != hashlib.sha256(directory.encode()).hexdigest():
            raise ValueError("Pack artwork directory does not match its filename")
        if not isinstance(record["banner"], str) or not re.fullmatch(r"banners/[0-9a-f]{64}\.png", record["banner"]):
            raise ValueError("Invalid pack banner name")
        packs[directory] = record["banner"]

    output.mkdir(parents=True, exist_ok=True)
    pack_art_used = set()
    old_art = {s["dir"]: s for s in (previous or {}).get("recent", []) if s.get("dir") and s.get("banner")}
    old_art.update(previous_songs)

    @lru_cache(maxsize=None)
    def copy_uploaded(name):
        if not re.fullmatch(r"banners/[0-9a-f]{64}\.png", name):
            raise ValueError("Invalid banner name")
        src = data_dir / name
        if src.is_file():
            raw = read_bytes(src, 256*1024)
        else:
            envelope = read_json(src.with_suffix(".json"), 400*1024)
            if set(envelope) != {"png_base64"}:
                raise ValueError("Invalid banner envelope")
            raw = base64.b64decode(envelope["png_base64"], validate=True)
            if len(raw) > 256*1024:
                raise ValueError("Banner too large")
        if hashlib.sha256(raw).hexdigest() != src.stem:
            raise ValueError("Banner hash mismatch")
        if builder.Image is None:
            raise ValueError("Pillow is required to validate banners")
        with builder.Image.open(io.BytesIO(raw)) as im:
            if im.format != "PNG" or max(im.size) > 320 or min(im.size) < 1:
                raise ValueError("Invalid banner image")
            im.verify()
        (output/"banners").mkdir(exist_ok=True)
        (output/name).write_bytes(raw)
        return name

    @lru_cache(maxsize=None)
    def banner(d):
        name = metadata.get(d, {}).get("banner")
        if name:
            return copy_uploaded(name)
        old = old_art.get(d, {})
        old_name = old.get("banner", "")
        historical = (Path(baseline)/old_name if baseline and
                      re.fullmatch(r"banners/[0-9a-f]+\.png", old_name) else None)
        # A pack can change its image, but cannot replace a known song image.
        pack_name = packs.get("/".join(d.split("/")[:2]) + "/")
        if pack_name and (old.get("bannerSource") == "pack" or not historical or not historical.is_file()):
            pack_art_used.add(d)
            return copy_uploaded(pack_name)
        if historical and historical.is_file() and not historical.is_symlink():
            (output/"banners").mkdir(exist_ok=True)
            shutil.copyfile(historical, output/old_name)
            if old.get("bannerSource") == "pack":
                pack_art_used.add(d)
            return old_name
        return ""

    with tempfile.TemporaryDirectory() as temp:
        save = Path(temp)/"Save"
        (save/"MachineProfile").mkdir(parents=True)
        uploads = save/"Upload"
        uploads.mkdir()
        shutil.copyfile(pdir/"Stats.xml", save/"MachineProfile"/"Stats.xml")
        seen = set()
        event_scores = {}
        for path in sorted((pdir/"events").glob("*.xml")):
            root = xml(path, 128*1024)
            records = root.findall("RecentSongScores/HighScoreForASongAndSteps")
            if len(records) != 1 or len(root) != 1:
                raise ValueError("Each event file must contain exactly one play")
            node = records[0]
            identity = event_identity(node)
            if path.stem != identity:
                raise ValueError("Event filename does not match its ID")
            hs = node.find("HighScore")
            if manifest.get("profile_kind") == "local" and builder.txt(hs, "PlayerGuid") != profile:
                raise ValueError("Play belongs to another profile")
            if not builder.txt(hs, "DateTime"):
                raise ValueError("Play is missing its timestamp")
            if identity in seen:
                raise ValueError("Duplicate event ID")
            seen.add(identity)
            song_node, steps_node = node.find("Song"), node.find("Steps")
            if song_node is None or steps_node is None:
                raise ValueError("Play is missing its song/chart")
            event_scores[builder.txt(hs, "Guid")] = (song_node.get("Dir", ""),
                steps_node.get("StepsType", ""), steps_node.get("Difficulty", "?"), builder.score_dict(hs))
            shutil.copyfile(path, uploads/path.name)
        if manifest.get("event_count", 0) > len(seen):
            raise ValueError("Export is missing play files")
        if previous:
            verify_published_events(previous, event_scores)
        builder.main(save_dir=str(save), out_dir=str(output), meta_override=meta,
                     banner_override=banner, sync=True)
    current = read_json(output/"data.json", 64*1024*1024)
    retention = {"chart_counters": [], "score_records": 0}
    if pack_art_used:
        for row in current["songs"] + current["recent"]:
            if row.get("dir") in pack_art_used:
                row["bannerSource"] = "pack"
    if previous:
        retention = preserve_published_history(previous, current)
        verify_history(previous, current)
        print(f"Retained published history: {len(retention['chart_counters'])} chart counters, "
              f"{retention['score_records']} score records")
        for counter in retention["chart_counters"]:
            print(f"  {counter['dir']} {counter['diff']}: {counter['uploaded']} uploaded, "
                  f"{counter['retained']} retained")
    if previous or pack_art_used:
        (output/"data.json").write_text(json.dumps(current, ensure_ascii=False, separators=(",", ":")))
    (output/"sync-status.json").write_text(json.dumps({
        "version": 1, "data_revision": revision, "profile_guid": profile,
        "generated": current["generated"], "recorded_plays": current["recordedPlays"],
        "history_retention": retention,
    }) + "\n")
    (output/".nojekyll").touch()
    return current


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("data")
    ap.add_argument("profile")
    ap.add_argument("output")
    ap.add_argument("--baseline")
    ap.add_argument("--revision", default="local")
    args = ap.parse_args()
    try:
        build(args.data, args.profile, args.output, args.baseline, args.revision)
    except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as exc:
        ap.exit(1, f"Dashboard import rejected: {exc}\n")

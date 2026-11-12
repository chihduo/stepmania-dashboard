#!/usr/bin/env python3
"""Validate a native StepMania export, then use the existing dashboard builder.

The data checkout is never imported or executed. Only the documented XML,
metadata JSON and PNG files are read. No liveDir deployment is used here.
"""
import argparse
import base64
import io
import hashlib
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


def xml(path, limit):
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
            validate_song_dir(node.get("Dir", ""))
    return root


def validate_song_dir(d):
    if not isinstance(d, str) or not d.startswith("Songs/") or len(d) > 2048 or "\\" in d or ".." in d.split("/"):
        raise ValueError("Invalid relative song directory")


def event_identity(node):
    hs = node.find("HighScore")
    guid = builder.txt(hs, "Guid")
    if not guid:
        raise ValueError("Exported play is missing its persistent Guid")
    # Exporter preserves original GUIDs and assigns deterministic legacy IDs.
    return hashlib.sha256(guid.encode()).hexdigest()


def verify_history(previous, current):
    """Reject a reset/wrong profile or a lossy replacement of a published site."""
    if previous.get("profile", {}).get("guid") != current["profile"]["guid"]:
        raise ValueError("Profile differs from published history; select the matching local profile")
    for key in ("songsPlayed", "tapsAndHolds", "jumps", "holds", "rolls", "mines", "hands", "lifts", "dancePoints", "gameplaySeconds", "sessions"):
        if current["totals"].get(key, 0) < previous.get("totals", {}).get(key, 0):
            raise ValueError(f"Historical total decreased: {key}; restore the complete Save history")
    songs = {s["dir"]: s for s in current["songs"]}
    for old in previous.get("songs", []):
        new = songs.get(old["dir"])
        if not new or new["plays"] < old["plays"]:
            raise ValueError("Historical song plays are missing; restore the complete profile")
    for key in ("playsDaily", "playsMonthly"):
        counts = dict(current.get(key, []))
        if any(counts.get(day, 0) < n for day, n in previous.get(key, [])):
            raise ValueError("Historical per-play logs are missing; restore Save/Upload")
    if current.get("recordedPlays", 0) < previous.get("recordedPlays", 0):
        raise ValueError("Historical per-play records decreased")


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
    stats = xml(pdir / "Stats.xml", 32*1024*1024)
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
            if set(c) - {"stepstype", "diff", "meter", "radar"} or not isinstance(c.get("meter"), int) or not 0 <= c["meter"] <= 1000:
                raise ValueError("Invalid chart metadata")
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

    output.mkdir(parents=True, exist_ok=True)
    (output / "banners").mkdir(exist_ok=True)
    def banner(d):
        name = metadata.get(d, {}).get("banner", "")
        if name:
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
        # Keep historical thumbnails when songs have been removed locally.
        old_name = previous_songs.get(d, {}).get("banner", "")
        if baseline and re.fullmatch(r"banners/[0-9a-f]+\.png", old_name):
            src = Path(baseline)/old_name
            if src.is_file() and not src.is_symlink():
                (output/"banners").mkdir(exist_ok=True)
                shutil.copyfile(src, output/old_name)
                return old_name
        return ""

    with tempfile.TemporaryDirectory() as temp:
        save = Path(temp)/"Save"
        (save/"MachineProfile").mkdir(parents=True)
        uploads = save/"Upload"
        uploads.mkdir()
        shutil.copyfile(pdir/"Stats.xml", save/"MachineProfile"/"Stats.xml")
        seen = set()
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
            shutil.copyfile(path, uploads/path.name)
        if manifest.get("event_count", 0) > len(seen):
            raise ValueError("Export is missing play files")
        builder.main(save_dir=str(save), out_dir=str(output), meta_override=meta,
                     banner_override=banner, sync=True)
    current = read_json(output/"data.json", 64*1024*1024)
    if previous:
        verify_history(previous, current)
    (output/"sync-status.json").write_text(json.dumps({
        "version": 1, "data_revision": revision, "profile_guid": profile,
        "generated": current["generated"], "recorded_plays": current["recordedPlays"],
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

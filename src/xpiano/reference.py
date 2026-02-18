from __future__ import annotations

import json
import math
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import mido

from xpiano import config, parser
from xpiano.schemas import validate


@dataclass
class SongInfo:
    song_id: str
    has_reference: bool
    segments: int
    updated_at: str | None


def songs_dir(data_dir: str | Path | None = None) -> Path:
    base = config.xpiano_home(data_dir)
    song_root = base / "songs"
    song_root.mkdir(parents=True, exist_ok=True)
    return song_root


def song_dir(song_id: str, data_dir: str | Path | None = None) -> Path:
    path = songs_dir(data_dir) / song_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _extract_midi_defaults(midi_path: Path) -> dict[str, Any]:
    mid = mido.MidiFile(str(midi_path))
    bpm = 120.0
    beats_per_measure = 4
    beat_unit = 4

    for msg in mido.merge_tracks(mid.tracks):
        if msg.type == "set_tempo":
            bpm = float(mido.tempo2bpm(msg.tempo))
            break
    for msg in mido.merge_tracks(mid.tracks):
        if msg.type == "time_signature":
            beats_per_measure = int(msg.numerator)
            beat_unit = int(msg.denominator)
            break

    beat_sec = 60.0 / bpm
    measures = max(
        1, int(math.ceil((mid.length / beat_sec) / beats_per_measure)))
    return {
        "bpm": round(bpm, 2),
        "beats_per_measure": beats_per_measure,
        "beat_unit": beat_unit,
        "measures": measures,
    }


def _default_meta(
    song_id: str,
    midi_defaults: dict[str, Any],
    data_dir: str | Path | None = None,
) -> dict[str, Any]:
    cfg = config.load_config(data_dir=data_dir)
    return {
        "song_id": song_id,
        "time_signature": {
            "beats_per_measure": midi_defaults["beats_per_measure"],
            "beat_unit": midi_defaults["beat_unit"],
        },
        "bpm": midi_defaults["bpm"],
        "segments": [
            {
                "segment_id": "default",
                "label": "default",
                "start_measure": 1,
                "end_measure": midi_defaults["measures"],
                "count_in_measures": 1,
            }
        ],
        "hand_split": {"split_pitch": 60},
        "tolerance": cfg["tolerance"],
    }


def import_reference(midi_path: str | Path, song_id: str, data_dir: str | Path | None = None) -> Path:
    src = Path(midi_path).expanduser()
    if not src.exists():
        raise FileNotFoundError(f"reference midi not found: {src}")

    target_song_dir = song_dir(song_id, data_dir=data_dir)
    target_ref = target_song_dir / "reference.mid"
    shutil.copy2(src, target_ref)

    notes = parser.midi_to_notes(target_ref)
    ref_notes_path = target_song_dir / "reference_notes.json"
    with ref_notes_path.open("w", encoding="utf-8") as fp:
        json.dump([asdict(n) for n in notes], fp, ensure_ascii=True, indent=2)

    meta_path = target_song_dir / "meta.json"
    if not meta_path.exists():
        defaults = _extract_midi_defaults(target_ref)
        save_meta(
            song_id=song_id,
            meta=_default_meta(song_id, defaults, data_dir=data_dir),
            data_dir=data_dir,
        )
    return target_ref


def save_meta(song_id: str, meta: dict[str, Any], data_dir: str | Path | None = None) -> Path:
    if meta.get("song_id") != song_id:
        meta = {**meta, "song_id": song_id}
    errors = validate("meta", meta)
    if errors:
        raise ValueError(f"invalid meta.json: {'; '.join(errors)}")
    path = song_dir(song_id, data_dir=data_dir) / "meta.json"
    with path.open("w", encoding="utf-8") as fp:
        json.dump(meta, fp, ensure_ascii=True, indent=2)
    return path


def load_meta(song_id: str, data_dir: str | Path | None = None) -> dict[str, Any]:
    path = song_dir(song_id, data_dir=data_dir) / "meta.json"
    if not path.exists():
        raise FileNotFoundError(f"meta.json missing for song: {song_id}")
    with path.open("r", encoding="utf-8") as fp:
        meta = json.load(fp)
    errors = validate("meta", meta)
    if errors:
        raise ValueError(f"invalid meta.json: {'; '.join(errors)}")
    return meta


def list_songs(data_dir: str | Path | None = None) -> list[SongInfo]:
    items: list[SongInfo] = []
    for item in sorted(songs_dir(data_dir).iterdir()):
        if not item.is_dir():
            continue
        meta_file = item / "meta.json"
        ref_file = item / "reference.mid"
        segments = 0
        if meta_file.exists():
            try:
                with meta_file.open("r", encoding="utf-8") as fp:
                    meta_data = json.load(fp)
                segments = len(meta_data.get("segments", []))
            except Exception:
                segments = 0
        updated_at = datetime.fromtimestamp(
            item.stat().st_mtime).isoformat(timespec="seconds")
        items.append(
            SongInfo(
                song_id=item.name,
                has_reference=ref_file.exists(),
                segments=segments,
                updated_at=updated_at,
            )
        )
    return items


def save_attempt(song_id: str, midi: mido.MidiFile, data_dir: str | Path | None = None) -> Path:
    attempts_dir = song_dir(song_id, data_dir=data_dir) / "attempts"
    attempts_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = attempts_dir / f"{ts}.mid"
    midi.save(str(output))
    return output

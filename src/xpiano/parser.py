from __future__ import annotations

from pathlib import Path
from typing import Literal

import pretty_midi

from xpiano.models import NoteEvent


def _to_hand(pitch: int, split_pitch: int) -> Literal["L", "R", "U"]:
    return "L" if pitch < split_pitch else "R"


def midi_to_notes(midi_path: str | Path, hand_split: int = 60) -> list[NoteEvent]:
    if hand_split < 0 or hand_split > 127:
        raise ValueError("hand_split must be between 0 and 127")
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    notes: list[NoteEvent] = []
    for instrument in midi.instruments:
        for note in instrument.notes:
            notes.append(
                NoteEvent(
                    pitch=note.pitch,
                    pitch_name=pretty_midi.note_number_to_name(note.pitch),
                    start_sec=float(note.start),
                    end_sec=float(note.end),
                    dur_sec=float(note.end - note.start),
                    velocity=int(note.velocity),
                    hand=_to_hand(note.pitch, hand_split),
                )
            )
    notes.sort(key=lambda n: (n.start_sec, n.pitch, n.end_sec))
    return notes

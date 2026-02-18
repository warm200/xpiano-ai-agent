from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

import mido

from xpiano.models import PlayResult


@dataclass
class MidiDevice:
    name: str
    kind: Literal["input", "output"]


def list_devices() -> list[MidiDevice]:
    devices: list[MidiDevice] = []
    try:
        devices.extend(MidiDevice(name=name, kind="input")
                       for name in mido.get_input_names())
    except Exception:
        pass
    try:
        devices.extend(MidiDevice(name=name, kind="output")
                       for name in mido.get_output_names())
    except Exception:
        pass
    return devices


def _click_count_in(count_in_beats: int, bpm: float, output_port: str | None) -> None:
    if count_in_beats <= 0 or output_port is None:
        return
    beat_sec = 60.0 / bpm
    with mido.open_output(output_port) as out_port:
        for _ in range(count_in_beats):
            out_port.send(mido.Message(
                "note_on", note=37, velocity=90, channel=9))
            time.sleep(min(0.08, beat_sec / 2))
            out_port.send(mido.Message(
                "note_off", note=37, velocity=0, channel=9))
            time.sleep(max(0.0, beat_sec - min(0.08, beat_sec / 2)))


def record(
    port: str | None,
    duration_sec: float,
    count_in_beats: int,
    bpm: float,
    output_port: str | None = None,
    beats_per_measure: int = 4,
    beat_unit: int = 4,
) -> mido.MidiFile:
    if duration_sec <= 0:
        raise ValueError("duration_sec must be > 0")
    if bpm <= 0:
        raise ValueError("bpm must be > 0")

    _click_count_in(count_in_beats=count_in_beats,
                    bpm=bpm, output_port=output_port)

    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    tempo = mido.bpm2tempo(bpm)
    track.append(mido.MetaMessage("set_tempo", tempo=tempo, time=0))
    track.append(
        mido.MetaMessage(
            "time_signature",
            numerator=beats_per_measure,
            denominator=beat_unit,
            time=0,
        )
    )

    start = time.monotonic()
    last_msg_time = start
    with mido.open_input(port) as in_port:
        while (time.monotonic() - start) < duration_sec:
            now = time.monotonic()
            pending = list(in_port.iter_pending())
            if not pending:
                time.sleep(0.001)
                continue
            for msg in pending:
                delta_sec = max(0.0, now - last_msg_time)
                delta_ticks = int(mido.second2tick(
                    delta_sec, midi.ticks_per_beat, tempo))
                if msg.is_meta:
                    continue
                track.append(msg.copy(time=delta_ticks))
                last_msg_time = now
    track.append(mido.MetaMessage("end_of_track", time=1))
    return midi


def _first_tempo(mid: mido.MidiFile, default_bpm: float = 120.0) -> float:
    for track in mid.tracks:
        for msg in track:
            if msg.type == "set_tempo":
                return mido.tempo2bpm(msg.tempo)
    return default_bpm


def play_midi(
    port: str | None,
    midi: mido.MidiFile,
    bpm: float | None = None,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    highlight_pitches: set[int] | None = None,
    velocity_boost: int = 40,
) -> PlayResult:
    outputs = []
    try:
        outputs = mido.get_output_names()
    except Exception:
        outputs = []
    if not outputs:
        return PlayResult(status="no_device", duration_sec=0.0)

    out_name = port or outputs[0]
    tempo = mido.bpm2tempo(_first_tempo(midi))
    speed_scale = 1.0
    if bpm and bpm > 0:
        speed_scale = _first_tempo(midi) / bpm

    now_sec = 0.0
    play_start = time.monotonic()
    with mido.open_output(out_name) as out_port:
        for msg in mido.merge_tracks(midi.tracks):
            delta_sec = mido.tick2second(msg.time, midi.ticks_per_beat, tempo)
            now_sec += delta_sec
            if msg.type == "set_tempo":
                tempo = msg.tempo
                continue
            if now_sec < start_sec:
                continue
            if end_sec is not None and now_sec > end_sec:
                break
            if delta_sec > 0:
                time.sleep(delta_sec * speed_scale)
            if msg.is_meta:
                continue
            out_msg = msg
            if highlight_pitches and msg.type == "note_on" and msg.velocity > 0 and msg.note in highlight_pitches:
                out_msg = msg.copy(velocity=min(
                    127, msg.velocity + velocity_boost))
            out_port.send(out_msg)
    return PlayResult(status="played", duration_sec=time.monotonic() - play_start)

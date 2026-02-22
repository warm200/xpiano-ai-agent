from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from math import inf, log

from xpiano.models import AlignmentResult, NoteEvent, ScorePosition


class Aligner(ABC):
    @abstractmethod
    def align_offline(self, ref: list[NoteEvent], attempt: list[NoteEvent]) -> AlignmentResult:
        """Offline alignment: post-recording analysis."""
        raise NotImplementedError

    def align_online(self, ref: list[NoteEvent]) -> OnlineAligner:
        raise NotImplementedError("Online alignment not available in MVP")


class OnlineAligner(ABC):
    @abstractmethod
    def feed(self, event: NoteEvent) -> ScorePosition:
        raise NotImplementedError


@dataclass
class _IndexedNote:
    idx: int
    note: NoteEvent


def _sequence_align_pairs(
    ref_onsets: list[float],
    attempt_onsets: list[float],
    gap_penalty_sec: float,
) -> tuple[list[tuple[int, int]], float]:
    m = len(ref_onsets)
    n = len(attempt_onsets)
    dp: list[list[float]] = [[inf] * (n + 1) for _ in range(m + 1)]
    back: list[list[str | None]] = [[None] * (n + 1) for _ in range(m + 1)]
    dp[0][0] = 0.0

    for i in range(1, m + 1):
        dp[i][0] = dp[i - 1][0] + gap_penalty_sec
        back[i][0] = "up"
    for j in range(1, n + 1):
        dp[0][j] = dp[0][j - 1] + gap_penalty_sec
        back[0][j] = "left"

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            match = dp[i - 1][j - 1] + \
                abs(ref_onsets[i - 1] - attempt_onsets[j - 1])
            skip_ref = dp[i - 1][j] + gap_penalty_sec
            skip_attempt = dp[i][j - 1] + gap_penalty_sec
            best = min(match, skip_ref, skip_attempt)
            dp[i][j] = best
            if best == match:
                back[i][j] = "diag"
            elif best == skip_ref:
                back[i][j] = "up"
            else:
                back[i][j] = "left"

    pairs: list[tuple[int, int]] = []
    i = m
    j = n
    while i > 0 or j > 0:
        step = back[i][j]
        if step == "diag":
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif step == "up":
            i -= 1
        elif step == "left":
            j -= 1
        else:
            break
    pairs.reverse()
    return pairs, dp[m][n]


def _estimate_affine_warp(
    ref: list[NoteEvent],
    attempt: list[NoteEvent],
    min_scale: float = 0.25,
    max_scale: float = 4.0,
) -> tuple[float, float]:
    if not ref or not attempt:
        return 1.0, 0.0
    ref_starts = [note.start_sec for note in ref]
    attempt_starts = [note.start_sec for note in attempt]
    ref_start = min(ref_starts)
    attempt_start = min(attempt_starts)
    ref_span = max(ref_starts) - ref_start
    attempt_span = max(attempt_starts) - attempt_start

    scale = 1.0
    if ref_span > 1e-6 and attempt_span > 1e-6:
        raw_scale = ref_span / attempt_span
        scale = max(min_scale, min(max_scale, raw_scale))
    offset = ref_start - (attempt_start * scale)
    return scale, offset


def _warp_attempt_start(start_sec: float, scale: float, offset_sec: float) -> float:
    return (start_sec * scale) + offset_sec


class DTWAligner(Aligner):
    def __init__(self, gap_penalty_sec: float = 0.20):
        self.gap_penalty_sec = gap_penalty_sec

    def align_offline(self, ref: list[NoteEvent], attempt: list[NoteEvent]) -> AlignmentResult:
        ref_by_pitch: dict[int, list[_IndexedNote]] = defaultdict(list)
        attempt_by_pitch: dict[int, list[_IndexedNote]] = defaultdict(list)

        for idx, note in enumerate(ref):
            ref_by_pitch[note.pitch].append(_IndexedNote(idx=idx, note=note))
        for idx, note in enumerate(attempt):
            attempt_by_pitch[note.pitch].append(
                _IndexedNote(idx=idx, note=note))

        merged_path: list[tuple[int, int]] = []
        total_cost = 0.0
        pitches = sorted(set(ref_by_pitch.keys()) |
                         set(attempt_by_pitch.keys()))

        for pitch in pitches:
            ref_bucket = ref_by_pitch.get(pitch, [])
            attempt_bucket = attempt_by_pitch.get(pitch, [])
            if not ref_bucket or not attempt_bucket:
                # Gap-only cost for unmatched notes.
                total_cost += (len(ref_bucket) +
                               len(attempt_bucket)) * self.gap_penalty_sec
                continue

            local_pairs, local_cost = _sequence_align_pairs(
                ref_onsets=[n.note.start_sec for n in ref_bucket],
                attempt_onsets=[n.note.start_sec for n in attempt_bucket],
                gap_penalty_sec=self.gap_penalty_sec,
            )
            total_cost += local_cost
            for ref_local_idx, attempt_local_idx in local_pairs:
                merged_path.append(
                    (
                        ref_bucket[ref_local_idx].idx,
                        attempt_bucket[attempt_local_idx].idx,
                    )
                )

        merged_path.sort()
        return AlignmentResult(path=merged_path, cost=total_cost, method="per_pitch_dtw")


class HMMAligner(Aligner):
    def __init__(
        self,
        delete_cost: float = 1.20,
        insert_cost: float = 1.20,
        onset_cost_weight: float = 8.0,
        duration_cost_weight: float = 0.20,
        match_reward: float = 0.20,
        max_onset_gap_sec: float = 2.50,
    ):
        self.delete_cost = delete_cost
        self.insert_cost = insert_cost
        self.onset_cost_weight = onset_cost_weight
        self.duration_cost_weight = duration_cost_weight
        self.match_reward = match_reward
        self.max_onset_gap_sec = max_onset_gap_sec

    def _match_cost(
        self,
        ref_note: NoteEvent,
        attempt_note: NoteEvent,
        warped_attempt_start: float,
    ) -> float:
        if ref_note.pitch != attempt_note.pitch:
            return inf

        onset_gap = abs(ref_note.start_sec - warped_attempt_start)
        if onset_gap > self.max_onset_gap_sec:
            return inf

        if ref_note.dur_sec > 0 and attempt_note.dur_sec > 0:
            duration_ratio = attempt_note.dur_sec / ref_note.dur_sec
            duration_penalty = abs(log(max(duration_ratio, 1e-9)))
        else:
            duration_penalty = 0.0

        raw_cost = (
            onset_gap * self.onset_cost_weight
            + duration_penalty * self.duration_cost_weight
            - self.match_reward
        )
        return max(0.0, raw_cost)

    def align_offline(
        self,
        ref: list[NoteEvent],
        attempt: list[NoteEvent],
    ) -> AlignmentResult:
        scale, offset_sec = _estimate_affine_warp(ref=ref, attempt=attempt)
        if not ref or not attempt:
            base_cost = (len(ref) * self.delete_cost) + (
                len(attempt) * self.insert_cost
            )
            return AlignmentResult(
                path=[],
                cost=base_cost,
                method="hmm_viterbi",
                warp_scale=scale,
                warp_offset_sec=offset_sec,
            )

        m = len(ref)
        n = len(attempt)
        dp: list[list[float]] = [[inf] * (n + 1) for _ in range(m + 1)]
        back: list[list[str | None]] = [[None] * (n + 1) for _ in range(m + 1)]
        dp[0][0] = 0.0

        for i in range(1, m + 1):
            dp[i][0] = dp[i - 1][0] + self.delete_cost
            back[i][0] = "up"
        for j in range(1, n + 1):
            dp[0][j] = dp[0][j - 1] + self.insert_cost
            back[0][j] = "left"

        warped_attempt_starts = [
            _warp_attempt_start(
                start_sec=note.start_sec,
                scale=scale,
                offset_sec=offset_sec,
            )
            for note in attempt
        ]

        for i in range(1, m + 1):
            ref_note = ref[i - 1]
            for j in range(1, n + 1):
                match_cost = self._match_cost(
                    ref_note=ref_note,
                    attempt_note=attempt[j - 1],
                    warped_attempt_start=warped_attempt_starts[j - 1],
                )
                match = dp[i - 1][j - 1] + match_cost
                skip_ref = dp[i - 1][j] + self.delete_cost
                skip_attempt = dp[i][j - 1] + self.insert_cost
                best = min(match, skip_ref, skip_attempt)
                dp[i][j] = best
                if best == match:
                    back[i][j] = "diag"
                elif best == skip_ref:
                    back[i][j] = "up"
                else:
                    back[i][j] = "left"

        i = m
        j = n
        path: list[tuple[int, int]] = []
        while i > 0 or j > 0:
            step = back[i][j]
            if step == "diag":
                ref_idx = i - 1
                attempt_idx = j - 1
                if ref[ref_idx].pitch == attempt[attempt_idx].pitch:
                    path.append((ref_idx, attempt_idx))
                i -= 1
                j -= 1
            elif step == "up":
                i -= 1
            elif step == "left":
                j -= 1
            else:
                break
        path.reverse()

        total_cost = dp[m][n]
        if total_cost == inf:
            total_cost = (m * self.delete_cost) + (n * self.insert_cost)

        return AlignmentResult(
            path=path,
            cost=total_cost,
            method="hmm_viterbi",
            warp_scale=scale,
            warp_offset_sec=offset_sec,
        )

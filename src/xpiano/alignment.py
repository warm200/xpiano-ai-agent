from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from math import inf

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

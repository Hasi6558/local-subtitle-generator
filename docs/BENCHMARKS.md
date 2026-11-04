# Local benchmark observations

Measured 4 November 2026 on Windows/Python 3.11.9, AMD Ryzen 7 5700U (8 cores,
16 logical CPUs), no CUDA device. Backend: faster-whisper 1.2.1 / CTranslate2
4.8.5; small multilingual snapshot 536b0662742c02347bc0e980a01041f333bce120.
Input: the first 36 seconds of the user's Japanese coffee-ordering clip, selected
global audio stream 1, explicit ja, CPU/int8, VAD enabled, default QC policy.
No sample media, transcripts, or weights are committed.

| Beam | Model instance | Total seconds | Inference seconds | Load seconds | Real-time factor | Peak process RSS (bytes) |
|---|---|---:|---:|---:|---:|---:|
| 1 | Cold | 10.757 | 8.378 | 1.587 | 0.299 | 774615040 |
| 1 | Warm | 8.635 | 8.044 | <0.001 | 0.240 | 774615040 |
| 5 | Cold | 13.512 | 11.300 | 1.477 | 0.375 | 774619136 |
| 5 | Warm | 12.158 | 11.569 | <0.001 | 0.338 | 774619136 |

Cold means a fresh model instance in a fresh preset worker, with weights already
cached locally. Warm reuses that loaded model in the same worker, with a new job
and no inference checkpoint reuse. OS disk cache was uncontrolled. Total excludes
worker startup, includes extraction/VAD/model/inference/QC/export, and is measured
by a monotonic clock. Stage timers cover named operations and exclude some manifest,
hash-validation and dispatch overhead; they need not sum exactly to total. Memory
is the worker's cumulative peak so far, including earlier repetitions; GPU VRAM is
unmeasured. This short test is not a full-movie runtime/memory forecast.

All four runs completed with zero structural errors and zero readability/QC
warnings on this short sample. That does not assess translation meaning. Human
meaning, timing and readability ratings remain unverified. Beam 1 was faster in
these runs; no quality superiority is established. Medium and CUDA were not tested.

Provisional local CPU test preset: small / cpu / int8 / beam 5 / VAD on, with
300-second chunk targets and 5-second overlap. This retains the measured baseline
behavior for review; beam 1 is a measured speed option. The application still
defaults to medium as the planned quality baseline, not a verified hardware quality
recommendation. A recommended quality preset requires source-language review and
representative difficult clips, plus full-movie acceptance.

Full machine-readable results and isolated worker logs are local:
`outputs/phase3-bench/benchmark-cec33eb9cced43a985a7d94049eeeb04/benchmark.json`.
Repeat the README benchmark command on the same samples to compare another
explicitly prepared model/device; keep results separated by source language.
Enter human observations separately rather than inferring them from text similarity
or the absence of QC flags.

The 650.540-second dialogue export has 171 cues, zero structural errors and 70
review issues: 8 long durations, 3 cues over two lines, 4 timestamp conflicts,
2 suspicious repetitions, and 53 preserved boundary/truncation flags. VAD temporal
coverage is heuristic, not translation accuracy or proof of completeness.
The supplied full-movie reference SRT has 886 cues, zero structural errors and
319 review warnings under these defaults. This is validation of the reference
file's structure/readability only; full-movie generated output remains unverified.

Phase 5 update: the supplied 7378.389-second movie subsequently completed direct
small/CPU/int8 inference with 25 chunks and 659 cues. Resume reused every completed
checkpoint; SRT/VTT structure and re-export passed. Recorded cumulative service
time was 941.396 seconds across attempts/resume, not a clean wall-clock benchmark:
a live schema upgrade interrupted the older worker and an unrecorded tail may be
absent. Mid-run observed process peak working set was 1,069,432,832 bytes. This
does not replace a controlled full-run peak-memory measurement. QC review issues
include long durations, boundary concerns and 11 VAD regions without output.
Human meaning and viewed synchronization remain unverified. Full local details
are in outputs/phase5-movie-gate.json; no runtime is generalized to other movies.

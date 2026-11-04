# Local text models and evaluation

Phase 6 adds an experimental contextual pipeline. **Whisper direct remains the
default.** No model has passed human semantic or viewed synchronization review.
Qwen3-4B is the initial contextual selection, not a demonstrated quality winner.
The UI also offers Qwen3-1.7B for a faster, smaller test. Neither requires Ollama.

## Hardware and runtime

Test PC, 4 November 2026: AMD Ryzen 7 5700U, 16 logical CPUs, approximately 16 GB
RAM, integrated AMD Radeon graphics, no NVIDIA CUDA device. Text inference uses
four CPU threads and zero GPU layers. Whisper is explicitly unloaded before the
text server starts; text inference is serialized with other jobs under the shared
worker lock. Automatic runtime preparation currently supports Windows x64 only.

Portable [llama.cpp b12099](https://github.com/ggml-org/llama.cpp/releases/tag/b12099),
commit `bee23322f`, MIT license. Tested executable reports version `0.8.0-dev`,
Clang 20.1.8, Windows x86_64. Asset `llama-b12099-bin-win-cpu-x64.zip`,
24,706,916 bytes, SHA-256
`ba751a91caeb8f5492c408386a46c9e0eba7da599c81bce1383260342e2b672b`.
Explicit preparation downloads and checksums this archive. Native inference uses
only loopback, a random port and per-run bearer key, no proxy, no web UI and local
GGUF files. A supervisor terminates the owned server when its worker disappears
or requests shutdown; batch requests poll cancellation.

The pinned [server documentation](https://github.com/ggml-org/llama.cpp/blob/b12099/tools/server/README.md)
describes JSON-schema response constraints. Real tests exercised chat completions
with a schema, `enable_thinking=false`, reasoning disabled, seed 42, temperature
0, a 4096-token context and at most 768 output tokens. Python independently
validates the exact ID set and types; schema-constrained output is not evidence
of faithful translation. Context is conservatively budgeted using UTF-8 bytes,
with room for output/template overhead; oversized targets fail without truncation.

## Exact shortlist

Both official GGUF repositories declare Apache-2.0. Model identity, download size
and SHA-256 are pinned in `src/local_subs/text_models.py`; inference verifies weight
hashes again and records the runtime/weight identity in each translation report.

| Selection | Official model | Revision | Quantization | Weight bytes |
| --- | --- | --- | --- | ---: |
| `qwen3-1.7b` | [Qwen/Qwen3-1.7B-GGUF](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF) | `90862c4b9d2787eaed51d12237eafdfe7c5f6077` | Q8_0 | 1,834,426,016 |
| `qwen3-4b` | [Qwen/Qwen3-4B-GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF) | `bc640142c66e1fdd12af0bd68f40445458f3869b` | Q4_K_M | 2,497,280,256 |

Files and checksums:

- `Qwen3-1.7B-Q8_0.gguf`:
  `061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a`
- `Qwen3-4B-Q4_K_M.gguf`:
  `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5`

## Configured pairs versus evaluated pairs

Speech recognition support still comes from faster-whisper's multilingual model
and tokenizer. Text translation uses a separate allowlist, based on the
[Qwen3 multilingual language list](https://qwenlm.github.io/blog/qwen3/).
This is a configuration claim, not a measured quality guarantee.

| Source → English | Contextual configuration | Project evaluation |
| --- | --- | --- |
| Japanese | Enabled | Both text candidates ran on the same 36.177-second clip; human review pending |
| Korean, Chinese, French, German, Spanish, Hindi | Enabled | No real-media contextual evaluation yet |
| English | Transcription only; text model skipped | Automated skip-path tests; no contextual translation needed |
| Other Whisper languages | Explicit contextual error | Direct mode remains an explicit user choice |

Alignment support is independent and has not been implemented or evaluated in
this phase. Timings remain the authoritative source-ASR segment timings; English
word timings are not inferred. Mixed-language dialogue remains a review concern.

## Measured short-clip comparison

Cached Small/int8 CPU speech model, beam 5, explicit Japanese, VAD enabled, same
36.177-second source/track/range. Contextual ASR produced 12 cues; direct produced
13. Both text candidates returned all 12 requested IDs in three batches of four,
with two neighbouring cues of context, no malformed-response retries, and no
structural export errors. Text model changes preserved every ASR checkpoint mtime.

| Path | Measured duration | Measured peak memory | Measurement scope |
| --- | ---: | ---: | --- |
| Whisper direct | 16.610 s | 776,192,000 bytes | Separate fresh benchmark worker; full generation, cached weights |
| Contextual text stage, 1.7B | 73.387 s | 2,534,510,592 bytes | Translation stage including weight verification/load; native server RSS only |
| Contextual text stage, 4B | 143.923 s | 5,113,933,824 bytes | Same source transcript; native server RSS only |

Text memory is sampled every 0.2 seconds from the native process's peak working
set. It excludes Python/speech processes and is not VRAM. The text-stage durations
exclude extraction/ASR. Direct and text memory scopes differ; do not compare them
as whole-application peaks. OS disk cache and background activity were uncontrolled.
The initial source ASR took 15.811 seconds of inference; an earlier localhost
sandbox failure is included in that job's cumulative manifest time. Consequently,
that manifest's total is not a clean contextual end-to-end benchmark. A clean
browser/queue acceptance run is recorded separately in `outputs/phase6-live-acceptance.json`.
That clean same-clip 4B run completed in **85.428 seconds total**, including
11.533 seconds of source inference and a 71.551-second text stage. Its native text
peak was 5,146,611,712 bytes. The paired direct job took 15.3 seconds. Variation
from the shortlist timings is substantial, so these single runs do not establish
a stable throughput or full-movie estimate. Browser inference, source review,
independent edits, toggle navigation and edited SRT/VTT export all passed.

Local evidence, intentionally ignored by Git to keep supplied media/transcripts
private: `outputs/phase6-evaluation/evaluation.json`, immutable exports under that
root, and `outputs/phase6-baseline/benchmark-*/benchmark.json`. The 4B-only resume
wall time was 146.777 seconds, including verification and cached speech setup.

Saved outputs diverge substantially at some cues. Questionable Japanese ASR words
propagate into different English interpretations in both candidates. Direct also
contains questionable wording. Five contextual flags mark katakana name/term
candidates; this deliberately noisy heuristic also catches ordinary loanwords and
does not detect all names. Glossary mismatches are flagged separately. Neither
flagging nor zero structural errors establishes fidelity, names, omissions, tone,
or synchronization. Those require source-language listening and human comparison.
No full-movie contextual performance or another source pair has been validated.

## Checkpoints and failure policy

Prompt `faithful-context-v1` treats dialogue/glossary as data, preserves ambiguity,
tone and negation, and forbids inventing names, gender or relationships. It sends
target/context IDs and text only; Python retains all timing. Translation cache
identity includes both languages, target/context IDs and text, glossary, prompt,
model revision/quantization/hash, runtime version, seed and token settings.
Affected translation batches rerun after a change; audio and source-ASR checkpoints
remain reusable. Changing between direct and contextual invalidates speech results
because the underlying Whisper task changes.

One malformed-response retry is the default (maximum two configurable retries).
Missing/duplicate/extra IDs or non-string/empty text fail validation. Completed
batches survive failure/cancellation; incomplete IDs and raw responses remain
inspectable. Failed translation never exports a partial English result or silently
falls back. The source SRT/JSON stays available. English input skips the text model.
Manual cue revisions and immutable generated exports remain independently retained.

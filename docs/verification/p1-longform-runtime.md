# P1.1 Longform and Runtime Hardening (v0.1.3)

Baseline: PR #9 merge commit 4f1021874be48350b680a957ca52ad2bf084fe59.

## Delivered

1. Opt-in verbatim source chunking via `planner.chunk_chars` and `config/llm-longform.yaml`. Default is disabled (0), preserving v0.1.2 single-request mode.
2. Explicit `planner.max_chunks` bounds possible charged LLM calls; every chunk goes through the original output grounding gate and a new source-retention/omitted-numeric gate.
3. All chunk Scene IDs are renumbered; the combined result is checked again, and failure prevents publishing a partial output.
4. Synchronous POSIX main-thread LLM calls are guarded by a SIGALRM deadline covering initial HTTP response and blocked stream reads; existing socket and monotonic checks remain.
5. Run-level cache now reuses `verify_manifest()` instead of trusting unsafe relative asset paths.
6. `scripts/prune_staging.py` previews stale abandoned/failed build directories by default and only deletes with `--delete`, a minimum age of one hour, valid filename, no manifest, and an unlocked run-specific flock.
7. Optional x264 preset/CRF/timeout settings and `config/fast-preview.yaml`; default production CFR settings remain 25 fps / veryfast / CRF 22.

## Example: explicit longform LLM mode

    # Configure the actual authorized OpenAI-compatible gateway via environment variables.
    news-video plan --input /path/to/long-news.md --config config/llm-longform.yaml
    news-video run --input /path/to/long-news.md --config config/llm-longform.yaml --out outputs

Only enable paid tiers after confirming the provider, model, credentials and budget. The example model gateway is not a preconfigured public endpoint.

## Example: explicit maintenance

    python scripts/prune_staging.py --out outputs --older-than-hours 24
    python scripts/prune_staging.py --out outputs --older-than-hours 24 --delete

The first command is dry-run. Completed outputs, live jobs, manifest-bearing staging, symlinks, and unknown paths are protected. This tool does not schedule automatic deletion. Stale folders after SIGKILL can be inspected and manually pruned once run locks are released.

## Example: fast preview (not production default)

    news-video run --input examples/sample_news.md --config config/fast-preview.yaml --out outputs

Preview uses 12 fps, ultrafast x264 and CRF 26, trading compression/compatibility and visual fidelity for a potential reduction in encoding cost. A long-form performance benchmark and platform playback test are still required; do not claim measured gains from configuration alone.

## Correctness and limits

- `split_source_chunks()` keeps every source character, prefers sentence punctuation, and creates no overlap that could accidentally repeat paragraphs. At a long punctuation-free segment a hard split can still occur.
- Each chunk must pass the existing output-to-source lexical grounding gate and a new source-to-output lexical-retention gate; missing numeric tokens are blocked. These rules DO NOT establish semantic truth, check Chinese numeric words, or prevent polarity reversals such as 增长 versus 下降.
- If any chunk, max-chunks limit, or global max-scenes limit fails, the overall run fails closed with no successful Manifest.
- SIGALRM deadline is POSIX main-thread only. It refuses to overwrite an existing SIGALRM timer. Windows native and non-main-thread service calls need a separate cancellable async timeout backend.
- The new cache check prevents reuse of a tampered or path-escaping Manifest, but cannot prove an adversary did not rewrite files AND all SHA-256 entries consistently. It is an integrity check, not a digital signature.
- FFmpeg remains CFR. An exploratory VFR experiment shortened encoding substantially but left video-stream duration inconsistent with the audio track; do not enable VFR without separate last-frame and video-track-duration verification.
- Native Windows fcntl, commercial Chinese TTS, Whisper, Docker build, dynamic Claude/Codex/OpenCode tests and a full iagent model-paid longform test remain out of scope or NOT RUN in this change.

## Verification required

- `PYTHONPATH=src pytest -q` for new longform, timeout, pruning, cache and render-option regression tests.
- `python scripts/validate_skills.py` and `python scripts/smoke_test.py --tier all-offline` in CI.
- Locally, test with real longform manuscripts and the authorized provider. Record per-chunk latency, actual Scene counts, retention, API call count/cost, total run time, and independent media QA; never claim those were tested in CI.
- Use ffprobe to verify both audio/video stream durations, timestamps and final-slide visibility before making any VFR optimization.

## Next priorities

Evidence-backed semantic fact checking (`SourceEvidence`/`StoryClaim`), backend-independent timeout/cancellation, measured video pipeline benchmarks, StageArtifact DAG, storage-quota policies, and licensed Chinese voice quality tests.

# Spike — can the scan path produce prompt segments?

Run 2026-08-15. **Verdict: no, and building it anyway would be actively harmful.
Do not implement. The current all-zero behaviour is correct.**

## Question

`analyze_request_prompt` is called from three sites, all in
`burnlens/proxy/interceptor.py`; `grep -rn 'prompt_' burnlens/scan/` returns nothing.
So `OversizedToolSchema`, `LowRAGEfficiency` and `HistoryBloat` never fire on
scan-derived rows — 99.6% of this user's 157k rows, and the whole dataset of any user
who onboards via `burnlens scan` without standing up the proxy.

Could the scanners reconstruct enough of the request body to fill the segments?

## What the agent logs actually contain

Inspected real files on this machine (keys and counts only, no content read).

| source | tool schemas | system prompt | messages |
|---|---|---|---|
| Claude Code `~/.claude/projects/**/*.jsonl` | **none** — 0 `input_schema`, 0 `tools` across 1,442 lines | **none** — `type:"system"` lines are `stop_hook_summary` / `turn_duration` telemetry, not the API `system` param | yes, one message per line |
| Codex `~/.codex/**/rollout-*.jsonl` | **none** | `session_meta.instructions`, populated in **182 of 400** sessions sampled (218 null) | yes, as `response_item` payloads |

**No agent logs tool definitions.** That is not an "unimplemented reader" — the data was
never written. `prompt_tools_tokens` is permanently unrecoverable from scan input, so
`OversizedToolSchema` can never work on scan data no matter how much reader code we add.

## Why a partial reconstruction is worse than none

`analyze_request_prompt` does not measure segments absolutely. It counts raw tokens per
section and then **proportionally scales them to sum to `input_tokens`**
(`prompt_analyzer.py:262`). Segments are *shares of the billed prompt*.

So a body missing its tools and system sections does not report zero for them — it
redistributes their mass onto whatever sections remain.

Measured, on a Claude-Code-shaped request (15 tool schemas, long system prompt, 20 turns
of history, `input_tokens=200,000`):

| segment | proxy (truth) | scan-rebuilt | error |
|---|---|---|---|
| `prompt_system_tokens` | 28,592 | 0 | −100% |
| `prompt_tools_tokens` | 94,146 | 0 | −100% |
| `prompt_history_tokens` | 77,198 | 199,836 | **+159%** |
| `prompt_user_tokens` | 64 | 164 | +156% |
| SUM | 200,000 | 200,000 | — |

Both sum to exactly `input_tokens`, because the scaler forces it. The output looks
perfectly well-formed and is wrong.

### That inflation crosses a detector threshold

`HistoryBloat` (`waste.py:570`) fires on `history >= 5_000 AND history/input_tokens >= 0.50`.

- Truth: `77,198 / 200,000 = 0.386` → correctly silent.
- Scan-rebuilt: `199,836 / 200,000 = 0.999` → **fires**.

With tools and system absent, history absorbs essentially the entire prompt on *every*
row, so this is not an edge case — `HistoryBloat` would fire on effectively every scan
row. Each finding carries `estimated_waste = cost_usd * 0.5`, so on this user's own
~$11k of scanned spend the dashboard would invent roughly **$5k of fabricated waste**.

Meanwhile `OversizedToolSchema` reads `tools/total = 0` and stays silent forever — a
false negative on the one detector the user most wants.

This is the project's recurring silent-wrongness class: a plausible number with nothing
checking it.

## Why today's behaviour is already correct

Scan rows carry `0` for every segment. `0 >= 5_000` is false, so all three detectors
decline to fire. **The current state is a safe abstention, not a bug.** Filling the
columns in partially is what converts safe silence into confident false findings.

## Recommendation

1. **Do not add prompt segmentation to the scanners.** Not as a reader improvement, not
   behind a flag. The missing sections are unrecoverable and the scaler launders their
   absence into wrong numbers on the sections that survive.
2. If scan users should be served here, the honest fix is **provenance, not
   reconstruction**: say in the UI/CLI that these three detectors require proxy-routed
   traffic. Small, truthful, and it stops the "why is /waste empty" question.
3. The real unlock for a scan user is routing through the proxy, which fills these
   columns correctly at capture time. That is a docs/onboarding problem, not a parser
   problem.

## If someone revisits this

Any future attempt must first answer: **where do the tool schemas come from?** Until an
agent starts logging them, `prompt_tools_tokens` is fiction, and because of the
proportional scaler, one fictional segment corrupts all the others. Segment-level
absolute counts (no scaling) would avoid the cross-contamination, but the detectors are
written as ratios against `input_tokens` and would need rewriting to consume them.

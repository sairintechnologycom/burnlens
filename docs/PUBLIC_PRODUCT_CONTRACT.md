# Public product contract

Canonical claims for every public BurnLens surface. Machine copy:
`frontend/src/lib/product-contract.json`. Pages and tests derive from that file.
If a page disagrees with the JSON, the page is wrong.

| Contract item | Canonical behaviour |
| --- | --- |
| Category | AI Economics Control Plane |
| Plain-language promise | Measure, explain and control the cost of AI agents and LLM applications. |
| First command | `burnlens scan` |
| Repo economics | `burnlens repos` |
| Cloud connect | `burnlens cloud connect` |
| Missing pricing | `$ unknown`, never silent `$0` |
| Scan attribution | Repository grain |
| Outcome metric | Cost per accepted outcome within a declared outcome unit; mixed units are separated |
| Coding outcome | Merged PR where GitHub data exists |
| Prompt content | Never uploaded to BurnLens Cloud |
| Cache | Off by default |
| Routing | Off by default |
| Savings | Projected ≠ observed cost reduction; current verification measures cost per request during a follow-up window and checks workflow acceptance when outcome evidence exists |
| Demo | Explicitly fixture/sample, not live telemetry |
| Self-service Cloud trial | 7-day, card required, $29/month |
| Agency pilot | 14-day guided evaluation, **not** a public SKU |

Dogfood figure (this repository, window 2026-07-10 to 2026-08-15, measured
2026-08-15): **$710.85** AI spend, **104** accepted PRs, **$6.84** per
accepted PR. A floor, not a ceiling — unpriced models count as `$ unknown`.

Guarded by `tests/test_public_truth.py` and `frontend/tests/product-contract.test.ts`.

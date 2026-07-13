# Contributing to BurnLens

Thanks for your interest in improving BurnLens! Issues and pull requests are welcome.

## Development setup

```bash
git clone https://github.com/sairintechnologycom/burnlens
cd burnlens
pip install -e ".[dev]"
pytest
```

## Ground rules

BurnLens is a transparent proxy in the request path of production applications. A few properties are non-negotiable:

1. **Local-first.** `burnlens start`, the proxy, SQLite storage, and the dashboard must work offline with no cloud account.
2. **Fail open.** If cost calculation, logging, or config fails, log a warning and forward the request anyway. Never break the user's app.
3. **Streaming passthrough.** Never buffer SSE responses — forward each chunk immediately.
4. **Transparent.** Never modify request or response bodies.
5. **Lightweight.** The proxy keeps a minimal dependency footprint; new runtime dependencies need a strong justification.

## Adding a provider

Providers are plugins: one new file in `burnlens/providers/` subclassing `Provider`, plus one pricing JSON in `burnlens/cost/pricing_data/`. No core changes required. See [docs/PROVIDERS.md](docs/PROVIDERS.md) for the full guide.

## Code style

- Type hints on all function signatures, docstrings on public functions
- `async`/`await` for all I/O
- Tests with `pytest` + `pytest-asyncio`; run `ruff check` and `mypy` before submitting

## Reporting issues

Include your Python version, BurnLens version (`pip show burnlens`), the provider you're proxying, and — if the issue involves a specific request — the model name and whether streaming was on. Never include API keys or prompt content in issue reports.

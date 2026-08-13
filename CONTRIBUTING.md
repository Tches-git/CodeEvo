# Contributing

## Development setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m ruff check codeevo tests scripts
python -m unittest discover -s tests -v
```

## Pull requests

- Keep changes scoped and include regression tests.
- Do not commit `.env`, API keys, private repository diffs, local databases, caches, or generated `output/` directories.
- Changes to Prompt, context budgets, routing or scoring must update the execution fingerprint and benchmark documentation.
- Do not run Holdout during ordinary tuning. A final Holdout run requires explicit confirmation and frozen configuration.
- Security findings should use the most specific applicable `CWE-NNN` identifier and cite a changed line.

## Reporting security issues

Do not open a public issue for credentials, authorization bypasses or sandbox escapes. Follow [docs/SECURITY.md](docs/SECURITY.md).

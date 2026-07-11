# Contributing

This package interacts with an unsupported authenticated web workflow. Keep
changes conservative: inspect browser traffic, test parsers and payloads, and
never add credentials or captured cookies to the repository.

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
```

All write methods must remain explicitly opt-in via `allow_writes=True`.

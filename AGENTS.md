# AGENTS.md

## Agent skills

### Issue tracker

Issues and specs live in this repo's GitHub Issues, managed with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five canonical labels as-is: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Development

Python 3.12, managed with [`uv`](https://docs.astral.sh/uv/).

- Set up: `uv sync` (core and CLI) or `uv sync --extra gui` (with the Qt app)
- Run: `uv run orteki --version`, `uv run orteki-app`
- Check everything CI checks, in CI's order (tests first without Qt, to prove the core and CLI work without it, then with the Qt app):
  `uv sync && uv run ruff check && uv run ruff format --check && uv run lint-imports && uv run pytest && uv sync --extra gui && QT_QPA_PLATFORM=offscreen uv run pytest && uv run basedpyright`

Rules:

- `orteki.core` must not import Qt, the CLI or the app; `orteki.cli` must not import Qt or the app. `lint-imports` enforces this.
- Commit messages and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, …). release-please uses them to version releases and write the changelog.
- Work on a branch and open a pull request against `trunk`; never push to `trunk` directly.

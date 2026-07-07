# Conflux — Developer Practices & Security Rules

This project is a Python-based crypto price alert bot (Binance/Bitget/OKX websockets → SQLite → Telegram notifications).

## Secrets & Credentials — Hard Rules

- NEVER hardcode API keys, bot tokens, private keys, or credentials into any source file, even temporarily.
- All secrets must go through environment variables (`.env` file, loaded via `python-dotenv`).
- `.env` must be in `.gitignore` before any commit that introduces it.
- Example/template config uses `.env.example` with placeholder values only (`TELEGRAM_BOT_TOKEN=your_token_here`).
- Before any `git add` or commit, check the diff for accidental secret patterns (long alphanumeric strings, `sk-`, `xox-`, etc.) — flag rather than commit.
- Never print/log secrets, even for debugging — mask or omit entirely.

## Branching & PR Flow

- No direct commits to `main`. Use `feature/<short-description>` or `fix/<short-description>` branches.
- One logical change per branch/PR — don't bundle unrelated changes.
- PR descriptions must state: what changed, why, and how it was tested.
- Self-review every diff before merging: check for secrets, debug prints, and dead commented-out code.

## Ticketing & Scope

- State the problem being solved before starting a change (issue or one-line note).
- Link PRs to issues when they exist.
- Don't silently fix unrelated bugs inline — note them separately (new issue or `TODO` with initials/date).

## High-Risk Files

- **`trigger_checker.py`** is the highest-risk file. Any PR touching it must explicitly re-verify: one-shot triggers, band-based logic, and gap-through detection match the locked spec.
- Exchange websocket message parsing changes require a note confirming field names were checked against current exchange API docs, not assumed from memory.

## Testing Expectations

- Changes to `check_trigger()` require manual test cases: price inside band, price outside band, price gapping through.
- New Telegram commands (alert create/delete) must be tested end-to-end in Telegram before merging.

## Prohibitions

- Do not disable `.gitignore` exclusions, even temporarily.
- Do not commit directly to `main`, even "just this once."
- Do not leave commented-out code in merged PRs — delete it; git history preserves it.
- Do not silently widen scope without flagging it in the PR description.

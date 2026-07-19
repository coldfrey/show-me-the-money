# Agent operating instructions

You are implementing `SPEC.md` in this repository. Read it fully before writing code. It contains verified API endpoints, exact response shapes, and a decompiled reference algorithm — trust it over your priors about the Elexon API.

## Loop protocol

1. Find the lowest-numbered milestone in SPEC.md §5 whose acceptance criteria do not yet pass (a milestone marked `M6 SKIPPED` in `PROGRESS.md` counts as passed). Work only on that milestone.
2. Implement task-by-task. Verification gates:
   - **After each task:** run the tests relevant to what you changed, then `uv run ruff check .` and the full `uv run pytest`. Both must be green before the task's commit.
   - **At milestone completion only:** additionally run `uv run ruff format --check .`, `uv run mypy src/`, and the milestone's acceptance commands from SPEC §5. All must pass to mark the milestone done. (Milestone acceptance commands are NOT expected to pass mid-milestone.)
3. Commit after each green task: `git commit -m "M<n>: <what>"`. Never commit with failing tests or lint errors.
4. Track progress in `PROGRESS.md`: one line per task — `[x] M2: turnup pro-rating + tests` — plus a "Next up" line so a fresh session can resume instantly. When a milestone completes, append a dated entry with evidence (actual numbers from the acceptance commands).
5. Stop conditions — write the problem to `BLOCKED.md` with full detail (command, output, what you tried) and stop, rather than guessing:
   - An Elexon endpoint persistently returns errors contradicting SPEC §3 (after the client's normal retries, on more than one date).
   - Milestone 4 validation deviation > 2% on any metric that remains unexplained after completing the M4 investigation procedure. (Explained deviations get a waiver per M4 + a METHODOLOGY.md entry, and are not blockers.)
   - An **acceptance step** genuinely cannot run without credentials you don't have. Note: Milestone 7's acceptance is entirely local — authoring the workflow YAML and R2 upload steps requires NO credentials and must not trigger this condition.
   - Milestone 6 is exempt: it can never block — after 3 failed fix attempts, record `M6 SKIPPED: <reason>` in `PROGRESS.md` and move to M7.

## Ground rules

- Live API calls are allowed and expected (open data, no key). All HTTP goes through `ElexonClient` — never bypass its throttle/cache with ad-hoc scripts.
- The `raw/` disk cache is sacred: computation must be reproducible offline from cache. Deleting `raw/` is never part of a fix. Never request or cache future settlement dates (SPEC §2 date bounds).
- **Purity rule (SPEC §2):** only `wastedwind.py` and `turnup.py` must be pure (no I/O, no clock). All other modules do I/O appropriate to their role — that is by design, not a violation.
- Any deviation from SPEC.md — however small — gets a line in `METHODOLOGY.md` under "Deviations".
- Do not add dependencies beyond those named in SPEC §2/§5 without recording why in `PROGRESS.md`. (`pyyaml` for waivers.yml and workflow-YAML validation is pre-approved.)
- Keep functions small and tested. When SPEC lists an edge case (M2's list), there must be a test named after it.
- Tests must not make live HTTP calls; use httpx MockTransport and `tmp_path` cache dirs. Live calls happen only in CLI acceptance commands.

## Verification quick reference

```
# per-task gate
uv run ruff check . && uv run pytest

# milestone gate (adds)
uv run ruff format --check . && uv run mypy src/

# acceptance (per SPEC §5)
uv run tracker --help
uv run tracker fetch --date 2026-07-10
uv run tracker ingest --date 2026-07-10 && uv run tracker show --date 2026-07-10
uv run tracker validate --year 2026 --month 6
uv run tracker validate --year 2026 --month 5
uv run tracker leaderboard --from 2026-06-01 --to 2026-06-30 --side turnup --by company --json
uv run tracker crosscheck --date 2026-07-10
uv run tracker export --date 2026-07-10 && uv run tracker export-summary
```

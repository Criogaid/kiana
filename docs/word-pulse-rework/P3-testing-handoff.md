# P3: background pipeline and command cutover

## Scope

Replaces the query-time bucket implementation with versioned background classification. `pipeline.py` consumes archive IDs, reconciles changed rules, retries failed classification twice, then falls back to literal labels on the third failure. Labels, unclassified counts, budget and progress commit together. Queries read stored labels and may request one optional trend sentence, but never classify messages.

`handlers.py`, `commands.py`, `report.py`, `jobs.py`, `config.py`, and the plugin entry replace the old command path. `ai.py` and `analysis.py` are removed. Startup drops the legacy charset and bucket tables while preserving theme names, clusters and aliases.

Public entry points include `pipeline.tick(now)`, `report.build_report(group_id, theme_name, window_days, now) -> ReportResult`, and typed rule/checkpoint operations in `db.py`. `db.load_report_data(...)` reads rules, cursor and all aggregates in one SQL snapshot. Core time conversion supports negative Unix timestamps on Windows.

## Evidence and implementation adjustments

- An actual reply segment causes NoneBot's regex rule to reject the quoted command before its handler runs. The entry uses `on_message` with a plaintext parsing rule to satisfy the plan's quoted-command requirement. Ordinary `词频很高` is rejected at the rule boundary.
- JSON-mode extraction now binds Word Pulse's error types, so malformed output reaches the pipeline retry/fallback path.
- Concurrent report reads and batch commits are serialized; a regression test pauses the reader and verifies its totals, ranking and timestamp all precede the queued write.
- The user authorized this assistant to migrate tests, overriding the original separate-testing assignment. Legacy tests were replaced, not retained through compatibility code.

## Verification

- `uv run ruff check`: passed.
- `uv run ruff format --check src/plugins/word_pulse`: passed (18 files).
- `uv run pyright`: passed (0 errors).
- `git diff --check`: passed.
- `uv run pytest -q`: **521 passed, 8 failed, 6 skipped**. All eight failures are the previously reproduced baseline failures in `tests/test_fund_matcher.py`; the full suite is not green. Live network tests remain opt-in and were not run.

Tests cover storage rollback and repeated cancellation, archive cursor bounds and batched lookups, rule versioning, migration from a legacy database, normalized name conflicts, atomic checkpoints, obsolete-version invisibility, backfill, budget fallback, AI retries, three provider protocols, invalid responses, permissions, actual quoted matcher routing, query caching and no query-time classification. `tests/conftest.py` resets the new schema, pipeline state and report caches.

## Pending environment example update

The user authorized a targeted example update, but the runtime permission policy still rejected reading `.env.prod` (`path_read`, rule `*.env.*`) on retry. Its Word Pulse example block still contains removed commands and configuration. The user explicitly approved merging P3 and proceeding with P4/P5 while this example update remains an outstanding final acceptance item. Replace only that example block with the following; do not modify live credentials or `.env.dev`:

```dotenv
# Word Pulse: background topic classification and read-only reports.
# Commands: 词频, 词频 <主题> [N天/周/月], 词频列表, 词频详情 <主题>
# Admin: 词频添加/移除/删除/别名添加/别名删除/说明/模式/候选
# word_pulse_plugin_enabled=false
# word_pulse_group_mode=all
# word_pulse_group_whitelist=[]
# word_pulse_group_blacklist=[]
# Configure shared AI routes word_pulse.classify and word_pulse.summary in ai_plugin_models.
# word_pulse_ai_daily_budget=2000
# word_pulse_ai_output_mode=strict
# word_pulse_tick_minutes=10
# word_pulse_backfill_days=7
# word_pulse_label_retention_days=31
# word_pulse_show_examples=false
```

Defaults and bounds are defined in [`config.py`](../../src/plugins/word_pulse/config.py). Update this example if those definitions change.

P4 candidate discovery and P5 chart rendering remain separate subsequent stages.

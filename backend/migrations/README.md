# Schema

## v2: hot/cold invoice archiving

`invoices` is a `UNION ALL` **view** over two identically shaped base tables:

- `invoices_hot` — working store; new invoices are inserted here.
- `invoices_cold` — archive store; only settled invoices arrive here.
- both carry an `INTEGER version` optimistic-lock column (starts at 1).
- the view exposes one extra `location TEXT` column (`'hot'` / `'cold'`).

Archive control tables:

- `archive_jobs` — one row per admin archive request: `upper_invoice_id`
  bound, status (`pending`/`moving`/`completed`/`failed`), cursor
  `last_invoice_id`, candidate/archived/skipped counters, `error`.
- `archive_job_items` — per-invoice ledger (`archived` / `skipped`), so every
  move and every skip is auditable.

The app creates this schema via `Base.metadata` plus
`src/services/schema_bootstrap.py` on startup; no separate migration runner is
needed.

### Upgrade from v1

A v1 database has a base *table* named `invoices` (no `version` column). On
bootstrap, when a relation named `invoices` of kind `r` is detected:

1. `invoices_hot` is created.
2. every legacy row is copied into `invoices_hot` with `version = 1`
   (`ON CONFLICT DO NOTHING`, so re-runs are safe).
3. the legacy table is dropped and replaced by the `invoices` view.

User edits and the 600-row fixture survive the upgrade unchanged.

## v1 (legacy)

SQLAlchemy metadata created `users` / `samples` / `batches` / `evidence` /
`audit`. `seed_demo` initialized the separate `invoices` fixture table and the
NOLOGIN `query_reader` role. Run `python -m scripts.seed_demo` for repeatable
initialization; natural keys preserve user edits.

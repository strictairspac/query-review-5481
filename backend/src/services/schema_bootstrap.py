"""Hot/cold invoice storage bootstrap.

invoices_hot and invoices_cold share the same shape (with an optimistic-lock
``version`` column). ``invoices`` is a UNION ALL view over both so every
existing statement keeps reading the full hot+cold dataset unchanged.
A legacy base-table ``invoices`` (schema v1) is migrated into the hot store
once, then replaced by the view.
"""
from sqlalchemy import text
from ..config.database import engine
HOT_DDL='''CREATE TABLE IF NOT EXISTS invoices_hot (
 invoice_id INTEGER PRIMARY KEY,
 customer TEXT NOT NULL,
 route TEXT NOT NULL,
 amount NUMERIC(12,2) NOT NULL,
 temperature NUMERIC(4,1) NOT NULL,
 status TEXT NOT NULL,
 version INTEGER NOT NULL DEFAULT 1
)'''
COLD_DDL=HOT_DDL.replace('invoices_hot','invoices_cold')
VIEW_DDL='''CREATE OR REPLACE VIEW invoices AS
 SELECT invoice_id,customer,route,amount,temperature,status,version,'hot' AS location FROM invoices_hot
 UNION ALL
 SELECT invoice_id,customer,route,amount,temperature,status,version,'cold' AS location FROM invoices_cold'''
MIGRATE_DDL='''DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relname='invoices' AND c.relkind='r') THEN
   EXECUTE $mig$%s$mig$;
   INSERT INTO invoices_hot (invoice_id,customer,route,amount,temperature,status,version)
   SELECT invoice_id,customer,route,amount,temperature,status,1 FROM invoices
   ON CONFLICT (invoice_id) DO NOTHING;
   DROP TABLE invoices;
 END IF;
END $$''' % HOT_DDL
GRANT_DDL='''DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='query_reader') THEN CREATE ROLE query_reader NOLOGIN; END IF;
END $$'''
def bootstrap():
    with engine.begin() as conn:
        conn.execute(text(MIGRATE_DDL))
        conn.execute(text(HOT_DDL))
        conn.execute(text(COLD_DDL))
        conn.execute(text(VIEW_DDL))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_hot_status_id ON invoices_hot(status,invoice_id)'))
        conn.execute(text('CREATE INDEX IF NOT EXISTS idx_cold_status_id ON invoices_cold(status,invoice_id)'))
        conn.execute(text(GRANT_DDL))
        # idempotent v2.1 column upgrade (only once the table exists)
        conn.execute(text("""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname='archive_jobs' AND relkind='r')
               AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                               WHERE table_name='archive_jobs' AND column_name='worker_heartbeat') THEN
                ALTER TABLE archive_jobs ADD COLUMN worker_heartbeat TIMESTAMP;
            END IF; END $$"""))
        conn.execute(text('GRANT SELECT ON invoices_hot,invoices_cold,invoices TO query_reader'))
        conn.execute(text('GRANT SELECT ON invoices_hot,invoices_cold,invoices TO query_reader'))

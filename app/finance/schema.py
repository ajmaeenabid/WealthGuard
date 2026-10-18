"""SQLite schema for the personal-finance module (plain SQL, no imports, so db.py can include it).

Money is stored as integer minor units (1 taka = 100 poisha) so no floating point ever touches an amount.
Every row belongs to a username; every query in the services filters on it.
"""
SQL = """
CREATE TABLE IF NOT EXISTS fin_settings (
  username TEXT PRIMARY KEY, base_currency TEXT NOT NULL DEFAULT 'BDT', created TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS fin_accounts (
  id TEXT PRIMARY KEY, username TEXT NOT NULL, name TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('cash','bank','savings','wallet','credit_card','investment','loan')),
  currency TEXT NOT NULL, opening_minor INTEGER NOT NULL DEFAULT 0, opening_date TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL,
  UNIQUE (username, name));

CREATE TABLE IF NOT EXISTS fin_transactions (
  id TEXT PRIMARY KEY, username TEXT NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('expense','income','refund','transfer','adjustment')),
  ts TEXT NOT NULL,
  account_id TEXT NOT NULL REFERENCES fin_accounts(id),
  to_account_id TEXT REFERENCES fin_accounts(id),
  direction TEXT CHECK (direction IN ('in','out')),
  merchant TEXT, item_name TEXT, quantity TEXT, unit_price_minor INTEGER,
  category TEXT, subcategory TEXT,
  gross_minor INTEGER NOT NULL CHECK (gross_minor >= 0),
  discount_minor INTEGER NOT NULL DEFAULT 0 CHECK (discount_minor >= 0),
  tax_minor INTEGER NOT NULL DEFAULT 0 CHECK (tax_minor >= 0),
  service_minor INTEGER NOT NULL DEFAULT 0 CHECK (service_minor >= 0),
  final_minor INTEGER NOT NULL CHECK (final_minor > 0),
  currency TEXT NOT NULL, payment_method TEXT, purpose TEXT,
  essential INTEGER CHECK (essential IN (0,1)), recurring INTEGER NOT NULL DEFAULT 0,
  obligation_id TEXT, goal_id TEXT, refund_of TEXT,
  tags TEXT NOT NULL DEFAULT '[]', note TEXT, receipt_ref TEXT,
  source TEXT NOT NULL CHECK (source IN ('voice','text','manual','import','assistant')),
  confidence REAL, confirmed INTEGER NOT NULL DEFAULT 1,
  idempotency_key TEXT, deleted_at TEXT, created TEXT NOT NULL, updated TEXT NOT NULL,
  UNIQUE (username, idempotency_key));
CREATE INDEX IF NOT EXISTS ix_fin_txn_user_ts ON fin_transactions (username, ts);
CREATE INDEX IF NOT EXISTS ix_fin_txn_user_acc ON fin_transactions (username, account_id);
CREATE INDEX IF NOT EXISTS ix_fin_txn_user_cat ON fin_transactions (username, category);
CREATE INDEX IF NOT EXISTS ix_fin_txn_user_merchant ON fin_transactions (username, merchant);

CREATE TABLE IF NOT EXISTS fin_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT, txn_id TEXT NOT NULL REFERENCES fin_transactions(id),
  name TEXT NOT NULL, quantity TEXT, unit_price_minor INTEGER, amount_minor INTEGER);

CREATE TABLE IF NOT EXISTS fin_budgets (
  id TEXT PRIMARY KEY, username TEXT NOT NULL, name TEXT NOT NULL, category TEXT,
  period TEXT NOT NULL CHECK (period IN ('weekly','monthly','custom')),
  start_date TEXT, end_date TEXT, limit_minor INTEGER NOT NULL CHECK (limit_minor > 0),
  currency TEXT NOT NULL, alert_pct INTEGER NOT NULL DEFAULT 80 CHECK (alert_pct BETWEEN 1 AND 200),
  active INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS fin_goals (
  id TEXT PRIMARY KEY, username TEXT NOT NULL, name TEXT NOT NULL, description TEXT,
  target_minor INTEGER NOT NULL CHECK (target_minor > 0), saved_minor INTEGER NOT NULL DEFAULT 0 CHECK (saved_minor >= 0),
  currency TEXT NOT NULL, target_date TEXT, priority INTEGER NOT NULL DEFAULT 2 CHECK (priority BETWEEN 1 AND 3),
  monthly_minor INTEGER CHECK (monthly_minor IS NULL OR monthly_minor >= 0), account_id TEXT REFERENCES fin_accounts(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed')),
  created TEXT NOT NULL, updated TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS fin_obligations (
  id TEXT PRIMARY KEY, username TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'bill',
  category TEXT, amount_minor INTEGER NOT NULL CHECK (amount_minor > 0), currency TEXT NOT NULL,
  recurrence TEXT NOT NULL CHECK (recurrence IN ('once','weekly','monthly','yearly')),
  next_due TEXT NOT NULL, reminder_days INTEGER NOT NULL DEFAULT 3, account_id TEXT REFERENCES fin_accounts(id),
  active INTEGER NOT NULL DEFAULT 1, created TEXT NOT NULL, updated TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS fin_obligation_payments (
  id TEXT PRIMARY KEY, obligation_id TEXT NOT NULL REFERENCES fin_obligations(id), due_date TEXT NOT NULL,
  txn_id TEXT REFERENCES fin_transactions(id), status TEXT NOT NULL CHECK (status IN ('paid','skipped')),
  amount_minor INTEGER, created TEXT NOT NULL, UNIQUE (obligation_id, due_date));

CREATE TABLE IF NOT EXISTS fin_sessions (
  id TEXT PRIMARY KEY, username TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('idle','collecting','awaiting_clarification','awaiting_confirmation','completed','cancelled')),
  intent TEXT, draft TEXT NOT NULL DEFAULT '{}', missing TEXT NOT NULL DEFAULT '[]', question TEXT, pending TEXT,
  created TEXT NOT NULL, updated TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_fin_sessions_user ON fin_sessions (username, updated);

CREATE TABLE IF NOT EXISTS fin_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES fin_sessions(id),
  role TEXT NOT NULL, text TEXT NOT NULL, ts TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS fin_requests (
  username TEXT NOT NULL, request_id TEXT NOT NULL, response TEXT NOT NULL, created TEXT NOT NULL,
  PRIMARY KEY (username, request_id));

CREATE TABLE IF NOT EXISTS fin_ai_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, username TEXT, purpose TEXT NOT NULL, model TEXT NOT NULL,
  prompt_version TEXT, correlation_id TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, est_cost_usd REAL,
  latency_ms INTEGER, retries INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS fin_reports (
  id TEXT PRIMARY KEY, username TEXT NOT NULL, kind TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL,
  payload TEXT NOT NULL, created TEXT NOT NULL);
"""

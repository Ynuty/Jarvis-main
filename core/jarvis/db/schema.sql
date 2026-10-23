-- ============================================================
--  Схема SQLite. Секреты здесь не лежат: только ссылки на записи
--  в хранилище учётных данных ОС (keyring / DPAPI).
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  avatar      TEXT NOT NULL DEFAULT '',
  pw_hash     TEXT NOT NULL,            -- argon2id
  pw_kind     TEXT NOT NULL DEFAULT 'pin',
  voice_phrase_hash TEXT,               -- необязательный вход по фразе
  created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  key         TEXT NOT NULL,
  value       TEXT NOT NULL,            -- JSON
  PRIMARY KEY (profile_id, key)
);

-- Журнал действий — единый источник правды: аудит, «Сделано Джарвисом», итог дня.
CREATE TABLE IF NOT EXISTS events (
  id          INTEGER PRIMARY KEY,
  ts          REAL NOT NULL,
  profile_id  INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
  skill       TEXT NOT NULL,
  tool        TEXT NOT NULL,
  args        TEXT NOT NULL DEFAULT '{}',
  risk        TEXT NOT NULL DEFAULT 'read',
  status      TEXT NOT NULL,            -- planned | confirmed | done | failed | cancelled | denied
  result      TEXT NOT NULL DEFAULT '',
  summary     TEXT NOT NULL DEFAULT '', -- человеческая строка для шторки
  source      TEXT NOT NULL DEFAULT 'user',
  task_id     INTEGER
);
CREATE INDEX IF NOT EXISTS events_ts ON events(profile_id, ts);

CREATE TABLE IF NOT EXISTS messages (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  ts          REAL NOT NULL,
  role        TEXT NOT NULL,            -- user | assistant
  text        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
  profile_id  INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
  text        TEXT NOT NULL,
  upto_id     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  fact        TEXT NOT NULL,
  category    TEXT NOT NULL DEFAULT 'общее',
  source      TEXT NOT NULL DEFAULT 'user',  -- user | extracted
  created_at  REAL NOT NULL,
  updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  text        TEXT NOT NULL,
  at          REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  due_at      REAL,
  duration    INTEGER NOT NULL DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'open',   -- open | done | cancelled
  repeat_rule TEXT NOT NULL DEFAULT '',
  created_by  TEXT NOT NULL DEFAULT 'user',   -- user | assistant
  created_at  REAL NOT NULL,
  done_at     REAL
);

CREATE TABLE IF NOT EXISTS carts (
  profile_id  INTEGER PRIMARY KEY REFERENCES profiles(id) ON DELETE CASCADE,
  shop        TEXT NOT NULL,
  items       TEXT NOT NULL,            -- JSON [{name, qty, unit}]
  updated_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  shop        TEXT NOT NULL,
  items       TEXT NOT NULL,
  ts          REAL NOT NULL,
  status      TEXT NOT NULL             -- opened | automated | cancelled
);

CREATE TABLE IF NOT EXISTS mail_accounts (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL,            -- imap | gmail
  address     TEXT NOT NULL,
  host        TEXT NOT NULL DEFAULT '',
  secret_ref  TEXT NOT NULL             -- имя записи в keyring
);

CREATE TABLE IF NOT EXISTS mail_moves (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  batch_id    TEXT NOT NULL,
  account_id  INTEGER NOT NULL,
  message_id  TEXT NOT NULL,
  from_folder TEXT NOT NULL,
  to_folder   TEXT NOT NULL,
  action      TEXT NOT NULL,            -- move | read | delete
  ts          REAL NOT NULL,
  undone      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rag_docs (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  path        TEXT NOT NULL DEFAULT '',
  added_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS rag_chunks (
  id          INTEGER PRIMARY KEY,
  doc_id      INTEGER NOT NULL REFERENCES rag_docs(id) ON DELETE CASCADE,
  idx         INTEGER NOT NULL,
  text        TEXT NOT NULL,
  emb         BLOB                      -- float32[]
);

-- Только при включённом согласии «собирать диалоги для дообучения».
CREATE TABLE IF NOT EXISTS dataset (
  id          INTEGER PRIMARY KEY,
  profile_id  INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  ts          REAL NOT NULL,
  messages    TEXT NOT NULL             -- JSON chat-формата
);

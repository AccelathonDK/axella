-- axella.dev report intake (Cloudflare D1, EU jurisdiction). No IP addresses, no account names anywhere.
CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY,              -- random UUID
  code TEXT UNIQUE NOT NULL,        -- what the reporter gets to follow it (status link)
  created TEXT NOT NULL,
  class TEXT NOT NULL,              -- critical | annoying | cosmetic | missing
  text TEXT NOT NULL,               -- what the reporter wrote (checked on their machine before sending)
  route TEXT, trail TEXT, errors TEXT, meta TEXT,   -- allow-listed JSON (src/schema.js)
  render BLOB,                      -- privacy render, when no R2 bucket is bound
  status TEXT NOT NULL DEFAULT 'new',   -- new | approved | merged | discarded
  issue_url TEXT, duplicate_of TEXT,
  install_hash TEXT                 -- sha256 of the random install token – for rate limiting only
);
CREATE INDEX IF NOT EXISTS reports_status ON reports(status, created);
CREATE TABLE IF NOT EXISTS replies (report_id TEXT PRIMARY KEY, address TEXT NOT NULL);   -- optional, never published
CREATE TABLE IF NOT EXISTS rate (who TEXT, day TEXT, n INTEGER, PRIMARY KEY (who, day));

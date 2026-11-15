-- Migration 002: Scanner tables for chat monitoring
-- Safe to run multiple times (idempotent)

-- Link messages to merchants
ALTER TABLE message_log ADD COLUMN IF NOT EXISTS merchant_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_msg_merchant ON message_log(merchant_id) WHERE merchant_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_msg_created ON message_log(created_at DESC);

-- Link groups to merchants
ALTER TABLE groups ADD COLUMN IF NOT EXISTS merchant_id BIGINT;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS auto_discovered BOOLEAN DEFAULT FALSE;

-- Cached AI summaries per merchant
CREATE TABLE IF NOT EXISTS merchant_chat_summaries (
    id SERIAL PRIMARY KEY,
    merchant_id BIGINT NOT NULL UNIQUE,
    summary_text TEXT NOT NULL,
    message_count INTEGER DEFAULT 0,
    last_message_at TIMESTAMP,
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    model_used TEXT DEFAULT 'gpt-4o-mini'
);
CREATE INDEX IF NOT EXISTS idx_chat_summary_merchant ON merchant_chat_summaries(merchant_id);

-- Scanner service state (health monitoring)
CREATE TABLE IF NOT EXISTS scanner_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

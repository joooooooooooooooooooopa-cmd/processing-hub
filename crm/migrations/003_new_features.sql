-- Migration 003: New features (auto-resolve, comparison, heatmap, exports)

-- Auto-resolve for incidents
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS auto_resolve_minutes INTEGER DEFAULT NULL;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS auto_resolve_metric_threshold DOUBLE PRECISION DEFAULT NULL;

-- Incident auto-resolve history
CREATE TABLE IF NOT EXISTS incident_auto_resolve_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incidents(id),
    resolved_reason TEXT NOT NULL,
    metric_value DOUBLE PRECISION,
    threshold DOUBLE PRECISION,
    resolved_at TIMESTAMPTZ DEFAULT NOW()
);

-- Heatmap data cache
CREATE TABLE IF NOT EXISTS analytics_heatmap_cache (
    id SERIAL PRIMARY KEY,
    metric TEXT NOT NULL,
    day_of_week INTEGER NOT NULL,  -- 0=Monday, 6=Sunday
    hour INTEGER NOT NULL,         -- 0-23
    value DOUBLE PRECISION NOT NULL,
    date TEXT NOT NULL,             -- YYYY-MM-DD
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(metric, day_of_week, hour, date)
);

-- Export history
CREATE TABLE IF NOT EXISTS export_history (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    export_type TEXT NOT NULL,     -- 'excel', 'pdf', 'csv'
    screen TEXT NOT NULL,          -- 'dashboard', 'traders', 'merchants', etc
    filters JSONB DEFAULT '{}',
    file_path TEXT,
    file_size INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_export_history_user ON export_history(user_id);
CREATE INDEX IF NOT EXISTS idx_heatmap_metric_date ON analytics_heatmap_cache(metric, date);
CREATE INDEX IF NOT EXISTS idx_auto_resolve_incident ON incident_auto_resolve_log(incident_id);

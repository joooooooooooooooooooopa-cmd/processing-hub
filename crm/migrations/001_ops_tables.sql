-- Phase 1: Incidents & Alerts System
-- Created: 2026-02-21
-- Idempotent: safe to run multiple times

-- Drop tables if they exist (clean state)
DROP TABLE IF EXISTS audit_log CASCADE;
DROP TABLE IF EXISTS alert_fires CASCADE;
DROP TABLE IF EXISTS incident_events CASCADE;
DROP TABLE IF EXISTS alerts CASCADE;
DROP TABLE IF EXISTS incidents CASCADE;

-- ============ INCIDENTS ============

CREATE TABLE incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Classification
    type TEXT NOT NULL,  -- conversion_drop, profit_drop, decline_spike, metabase_timeout, data_gap
    severity TEXT NOT NULL CHECK (severity IN ('P0', 'P1', 'P2', 'P3')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'ack', 'resolved', 'reopened')),
    scope TEXT NOT NULL,  -- global, merchant, method, bank, provider, team, trader, tl, htl, agent

    -- Metric details
    metric TEXT NOT NULL,  -- conversion_success, conversion_issued, profit, turnover, issued_req, decline_pct, etc.
    baseline_value NUMERIC,
    current_value NUMERIC NOT NULL,
    delta_value NUMERIC,
    delta_pct NUMERIC,

    -- Time window
    period_from TIMESTAMPTZ NOT NULL,
    period_to TIMESTAMPTZ NOT NULL,

    -- Dimensions (JSON for flexibility)
    dimensions JSONB NOT NULL DEFAULT '{}',  -- {merchant_id, merchant_name, payment_type, bank, provider_name, trader, tla, htl, agent}

    -- Description
    title TEXT NOT NULL,
    description TEXT,

    -- Ownership
    owner_user_id UUID,
    created_by TEXT NOT NULL DEFAULT 'rule',  -- rule | user | system
    rule_id UUID,

    -- Dedupe
    dedupe_key TEXT NOT NULL,

    -- Lifecycle timestamps
    ack_at TIMESTAMPTZ,
    resolved_at TIMESTAMPTZ,
    next_review_at TIMESTAMPTZ,

    -- Muting
    is_muted BOOLEAN NOT NULL DEFAULT FALSE,
    mute_until TIMESTAMPTZ,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for incidents
CREATE INDEX idx_incidents_status_severity ON incidents(status, severity, created_at DESC);
CREATE INDEX idx_incidents_dedupe ON incidents(dedupe_key);
CREATE INDEX idx_incidents_created_at ON incidents(created_at DESC);
CREATE INDEX idx_incidents_type ON incidents(type);
CREATE INDEX idx_incidents_scope ON incidents(scope);
CREATE INDEX idx_incidents_metric ON incidents(metric);
CREATE INDEX idx_incidents_owner ON incidents(owner_user_id) WHERE owner_user_id IS NOT NULL;

-- GIN index for dimensions JSONB (optional, for advanced filtering)
CREATE INDEX idx_incidents_dimensions ON incidents USING GIN (dimensions);

-- ============ INCIDENT EVENTS ============

CREATE TABLE incident_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id UUID NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,

    event_type TEXT NOT NULL,  -- created, refreshed, ack, resolve, reopen, assign, comment, mute, unmute
    actor_user_id UUID,
    payload JSONB NOT NULL DEFAULT '{}',  -- {comment, prev_owner, new_owner, mute_minutes, etc.}

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for incident_events
CREATE INDEX idx_incident_events_incident ON incident_events(incident_id, created_at DESC);
CREATE INDEX idx_incident_events_created_at ON incident_events(created_at DESC);

-- ============ ALERTS ============

CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Alert config
    name TEXT NOT NULL,
    metric TEXT NOT NULL,  -- conversion_success, profit, decline_pct, etc.
    severity TEXT NOT NULL CHECK (severity IN ('P0', 'P1', 'P2', 'P3')),
    scope TEXT NOT NULL,  -- global, merchant, method, bank, provider, team

    -- Condition (JSON for flexibility)
    condition JSONB NOT NULL,  -- {"op": "<", "threshold": 0.20} OR {"op": "delta_pct", "threshold": -15}

    -- Time window
    time_window JSONB NOT NULL,  -- {"minutes": 60}

    -- Filters (for dimensioned alerts)
    filters JSONB NOT NULL DEFAULT '{}',  -- {"method": "SBP", "bank": "Альфа Банк"}

    -- Notification config
    recipients JSONB NOT NULL DEFAULT '{}',  -- {"roles": ["ops"], "user_ids": [...], "chats": [...]}

    -- Cooldown
    cooldown_minutes INTEGER NOT NULL DEFAULT 15,

    -- Status
    enabled BOOLEAN NOT NULL DEFAULT TRUE,

    -- Audit
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for alerts
CREATE INDEX idx_alerts_enabled ON alerts(enabled) WHERE enabled = TRUE;
CREATE INDEX idx_alerts_metric ON alerts(metric);

-- ============ ALERT FIRES ============

CREATE TABLE alert_fires (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id UUID NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,

    fired_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Context (snapshot of values at fire time)
    context JSONB NOT NULL,  -- {baseline_value, current_value, delta_value, delta_pct, dimensions}

    -- Link to incident
    incident_id UUID REFERENCES incidents(id),

    -- Delivery status
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    delivered_at TIMESTAMPTZ,
    delivery_errors TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for alert_fires
CREATE INDEX idx_alert_fires_alert ON alert_fires(alert_id, fired_at DESC);
CREATE INDEX idx_alert_fires_incident ON alert_fires(incident_id) WHERE incident_id IS NOT NULL;
CREATE INDEX idx_alert_fires_fired_at ON alert_fires(fired_at DESC);

-- ============ AUDIT LOG ============

CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID,
    action TEXT NOT NULL,  -- incident.ack, incident.resolve, alert.create, alert.toggle, etc.
    resource_type TEXT NOT NULL,  -- incident, alert, etc.
    resource_id TEXT NOT NULL,

    payload JSONB NOT NULL DEFAULT '{}',  -- {prev_value, new_value, comment, etc.}

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for audit_log
CREATE INDEX idx_audit_log_user ON audit_log(user_id) WHERE user_id IS NOT NULL;
CREATE INDEX idx_audit_log_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at DESC);

-- ============ FUNCTIONS ============

-- Auto-update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Triggers for auto-updating updated_at
DROP TRIGGER IF EXISTS update_incidents_updated_at ON incidents;
CREATE TRIGGER update_incidents_updated_at
    BEFORE UPDATE ON incidents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_alerts_updated_at ON alerts;
CREATE TRIGGER update_alerts_updated_at
    BEFORE UPDATE ON alerts
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============ SEED DATA (Default Alerts) ============

-- Only insert if alerts table is empty
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM alerts LIMIT 1) THEN

        -- Alert 1: Conversion Success Drop (P1)
        INSERT INTO alerts (name, metric, severity, scope, condition, time_window, recipients, cooldown_minutes, enabled)
        VALUES (
            'Конверсия в успех упала',
            'conversion_success',
            'P1',
            'global',
            '{"op": "delta_pct", "threshold": -20}'::jsonb,
            '{"minutes": 60}'::jsonb,
            '{"roles": ["ops", "admin"]}'::jsonb,
            15,
            TRUE
        );

        -- Alert 2: Profit Drop (P1)
        INSERT INTO alerts (name, metric, severity, scope, condition, time_window, recipients, cooldown_minutes, enabled)
        VALUES (
            'Прибыль упала',
            'profit',
            'P1',
            'global',
            '{"op": "delta_pct", "threshold": -20}'::jsonb,
            '{"minutes": 60}'::jsonb,
            '{"roles": ["ops", "admin"]}'::jsonb,
            15,
            TRUE
        );

        -- Alert 3: Decline Spike (P1)
        INSERT INTO alerts (name, metric, severity, scope, condition, time_window, recipients, cooldown_minutes, enabled)
        VALUES (
            'Рост отказов',
            'decline_pct',
            'P1',
            'global',
            '{"op": "spike", "multiplier": 2}'::jsonb,
            '{"minutes": 60}'::jsonb,
            '{"roles": ["ops", "admin"]}'::jsonb,
            15,
            TRUE
        );

        RAISE NOTICE 'Seeded 3 default alerts';
    END IF;
END $$;

-- ============ COMMENTS ============

COMMENT ON TABLE incidents IS 'Operational incidents with lifecycle tracking';
COMMENT ON TABLE incident_events IS 'Timeline of incident state changes';
COMMENT ON TABLE alerts IS 'Alert rules and configuration';
COMMENT ON TABLE alert_fires IS 'History of alert triggers';
COMMENT ON TABLE audit_log IS 'Audit trail for sensitive operations';

COMMENT ON COLUMN incidents.dedupe_key IS 'Unique key for deduplication: type|scope|metric|dims|window';
COMMENT ON COLUMN incidents.dimensions IS 'Context dimensions: {merchant_id, method, bank, trader, etc.}';
COMMENT ON COLUMN alerts.condition IS 'Condition JSON: {"op": "delta_pct", "threshold": -20}';
COMMENT ON COLUMN alerts.time_window IS 'Time window JSON: {"minutes": 60}';
COMMENT ON COLUMN alert_fires.context IS 'Snapshot: {baseline, current, delta, dimensions}';

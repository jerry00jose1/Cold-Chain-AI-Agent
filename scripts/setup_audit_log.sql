-- Audit log for dispatcher sessions.
-- The agent login can insert rows. It cannot read them.
-- The admin login can read them.

CREATE TABLE IF NOT EXISTS fde_views.agent_audit_log (
    log_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    logged_at  timestamptz NOT NULL DEFAULT now(),
    session_id text,
    node_name  text,
    tool_name  text,
    content    text
);

GRANT USAGE ON SCHEMA fde_views TO jerry;
GRANT SELECT ON fde_views.agent_audit_log TO jerry;

GRANT INSERT ON fde_views.agent_audit_log TO usr_fde_ro;
GRANT USAGE, SELECT ON SEQUENCE fde_views.agent_audit_log_log_id_seq TO usr_fde_ro;

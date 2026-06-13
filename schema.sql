-- ============================================================
-- CockroachDB Schema for CrewAI + CockroachDB PoC
-- ============================================================
-- Run this manually to pre-initialize the schema,
-- OR let main.py call init_db() which creates tables automatically.
--
-- Connect to your cluster:
--   cockroach sql --url "postgresql://..."
-- Then run:
--   \i schema.sql
-- ============================================================

-- Agent Workflows
-- Tracks each CrewAI workflow execution from start to finish.
CREATE TABLE IF NOT EXISTS agent_workflows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_name STRING NOT NULL,
    status STRING DEFAULT 'pending',        -- pending | running | completed | failed
    input_data JSONB,                        -- Full input payload (claim details, etc.)
    started_at TIMESTAMP DEFAULT now(),
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    INDEX idx_workflow_status (status),
    INDEX idx_workflow_name (workflow_name),
    INDEX idx_workflow_created_at (created_at)
);

-- Agent Actions
-- Stores every individual agent decision and output.
CREATE TABLE IF NOT EXISTS agent_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID REFERENCES agent_workflows(id) ON DELETE CASCADE,
    agent_name STRING NOT NULL,
    task_name STRING NOT NULL,
    input_data JSONB,                        -- Task input
    output_data TEXT,                        -- Agent's full output text
    status STRING DEFAULT 'pending',        -- pending | running | completed | failed
    started_at TIMESTAMP DEFAULT now(),
    completed_at TIMESTAMP,
    INDEX idx_action_workflow (workflow_id),
    INDEX idx_action_agent (agent_name),
    INDEX idx_action_status (status)
);

-- Human Approval Queue
-- Human-in-the-loop: agent recommends, human approves, agent executes.
CREATE TABLE IF NOT EXISTS approval_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID REFERENCES agent_workflows(id) ON DELETE CASCADE,
    action_id UUID REFERENCES agent_actions(id) ON DELETE CASCADE,
    recommendation TEXT NOT NULL,            -- AI recommendation text
    status STRING DEFAULT 'pending',        -- pending | approved | rejected | escalated
    reviewer STRING,                         -- Email/ID of human reviewer
    reviewer_comments TEXT,
    reviewed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    INDEX idx_approval_status (status),
    INDEX idx_approval_workflow (workflow_id),
    INDEX idx_approval_created_at (created_at)
);

-- Audit Log
-- Immutable record of all agent and human actions.
-- This is the governance & compliance layer.
CREATE TABLE IF NOT EXISTS audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_id UUID,
    event_type STRING NOT NULL,              -- WORKFLOW_STARTED, AGENT_ACTION_COMPLETED, etc.
    event_data JSONB,                        -- Full event context
    actor STRING DEFAULT 'system',          -- system | human email
    timestamp TIMESTAMP DEFAULT now(),
    INDEX idx_audit_workflow (workflow_id),
    INDEX idx_audit_event_type (event_type),
    INDEX idx_audit_timestamp (timestamp)
);

-- ── Useful Queries ──────────────────────────────────────────

-- View all pending approvals:
-- SELECT aq.id, aw.workflow_name, aq.recommendation, aq.created_at
-- FROM approval_queue aq
-- JOIN agent_workflows aw ON aq.workflow_id = aw.id
-- WHERE aq.status = 'pending';

-- Full audit trail for a specific workflow:
-- SELECT event_type, actor, timestamp, event_data
-- FROM audit_log
-- WHERE workflow_id = '<your-workflow-id>'
-- ORDER BY timestamp ASC;

-- Agent performance summary:
-- SELECT agent_name, COUNT(*) as actions, AVG(EXTRACT(EPOCH FROM (completed_at - started_at))) as avg_seconds
-- FROM agent_actions
-- WHERE status = 'completed'
-- GROUP BY agent_name;

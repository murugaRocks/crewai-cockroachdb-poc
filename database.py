"""
database.py
-----------
CockroachDB connection and data access layer for the CrewAI PoC.

This module handles:
  - Connection management
  - Schema initialization
  - Workflow lifecycle (create, update, complete)
  - Agent action persistence
  - Human-in-the-loop approval queue
  - Immutable audit logging
"""

import os
import psycopg2
from psycopg2.extras import Json
from dotenv import load_dotenv

load_dotenv()


# ── Connection ───────────────────────────────────────────────

def get_connection():
    """
    Create and return a connection to CockroachDB.
    Reads COCKROACHDB_URL from the environment.
    """
    connection_string = os.getenv("COCKROACHDB_URL")
    if not connection_string:
        raise ValueError(
            "COCKROACHDB_URL environment variable is not set.\n"
            "Add it to your .env file:\n"
            "  COCKROACHDB_URL=postgresql://user:pass@host:26257/defaultdb?sslmode=verify-full"
        )
    conn = psycopg2.connect(connection_string)
    conn.autocommit = True
    return conn


# ── Schema Initialization ────────────────────────────────────

def init_db(conn):
    """
    Create all required tables if they don't already exist.
    Safe to call on every startup (idempotent).
    """
    with conn.cursor() as cur:
        # Workflow tracking
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_workflows (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_name STRING NOT NULL,
                status STRING DEFAULT 'pending',
                input_data JSONB,
                started_at TIMESTAMP DEFAULT now(),
                completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT now(),
                INDEX idx_workflow_status (status),
                INDEX idx_workflow_name (workflow_name)
            )
        """)

        # Individual agent actions
        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_actions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID REFERENCES agent_workflows(id) ON DELETE CASCADE,
                agent_name STRING NOT NULL,
                task_name STRING NOT NULL,
                input_data JSONB,
                output_data TEXT,
                status STRING DEFAULT 'pending',
                started_at TIMESTAMP DEFAULT now(),
                completed_at TIMESTAMP,
                INDEX idx_action_workflow (workflow_id),
                INDEX idx_action_agent (agent_name)
            )
        """)

        # Human-in-the-loop approvals
        cur.execute("""
            CREATE TABLE IF NOT EXISTS approval_queue (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID REFERENCES agent_workflows(id) ON DELETE CASCADE,
                action_id UUID REFERENCES agent_actions(id) ON DELETE CASCADE,
                recommendation TEXT NOT NULL,
                status STRING DEFAULT 'pending',
                reviewer STRING,
                reviewer_comments TEXT,
                reviewed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT now(),
                INDEX idx_approval_status (status),
                INDEX idx_approval_workflow (workflow_id)
            )
        """)

        # Immutable audit log
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID,
                event_type STRING NOT NULL,
                event_data JSONB,
                actor STRING DEFAULT 'system',
                timestamp TIMESTAMP DEFAULT now(),
                INDEX idx_audit_workflow (workflow_id),
                INDEX idx_audit_event_type (event_type),
                INDEX idx_audit_timestamp (timestamp)
            )
        """)

    print("✅ CockroachDB schema initialized successfully")


# ── Workflow Lifecycle ───────────────────────────────────────

def create_workflow(conn, workflow_name: str, input_data: dict) -> str:
    """
    Insert a new workflow record and return its UUID.
    Called at the start of every CrewAI run.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_workflows (workflow_name, input_data, status)
            VALUES (%s, %s, 'running')
            RETURNING id
            """,
            (workflow_name, Json(input_data))
        )
        workflow_id = str(cur.fetchone()[0])

    log_audit_event(conn, workflow_id, "WORKFLOW_STARTED", {
        "workflow_name": workflow_name,
        "input_summary": str(input_data)[:500]
    })
    return workflow_id


def complete_workflow(conn, workflow_id: str, status: str = "completed"):
    """
    Mark a workflow as complete (or failed).
    Updates the completed_at timestamp.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_workflows
            SET status = %s, completed_at = now()
            WHERE id = %s
            """,
            (status, workflow_id)
        )
    log_audit_event(conn, workflow_id, "WORKFLOW_COMPLETED", {"final_status": status})


# ── Agent Actions ────────────────────────────────────────────

def save_agent_action(
    conn,
    workflow_id: str,
    agent_name: str,
    task_name: str,
    input_data: dict,
    output: str
) -> str:
    """
    Persist an agent's completed task output to CockroachDB.
    Returns the action UUID.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_actions
                (workflow_id, agent_name, task_name, input_data, output_data, status, completed_at)
            VALUES (%s, %s, %s, %s, %s, 'completed', now())
            RETURNING id
            """,
            (workflow_id, agent_name, task_name, Json(input_data), output)
        )
        action_id = str(cur.fetchone()[0])

    log_audit_event(conn, workflow_id, "AGENT_ACTION_COMPLETED", {
        "agent": agent_name,
        "task": task_name,
        "output_preview": output[:300] if output else ""
    })
    return action_id


# ── Human-in-the-Loop ────────────────────────────────────────

def create_approval_request(
    conn,
    workflow_id: str,
    action_id: str,
    recommendation: str
) -> str:
    """
    Queue an AI recommendation for human review.
    Returns the approval request UUID.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO approval_queue (workflow_id, action_id, recommendation, status)
            VALUES (%s, %s, %s, 'pending')
            RETURNING id
            """,
            (workflow_id, action_id, recommendation)
        )
        approval_id = str(cur.fetchone()[0])

    log_audit_event(conn, workflow_id, "APPROVAL_REQUESTED", {
        "approval_id": approval_id,
        "recommendation_preview": recommendation[:300]
    })
    return approval_id


def process_approval(
    conn,
    approval_id: str,
    status: str,
    reviewer: str,
    comments: str = ""
):
    """
    Record a human reviewer's decision on an approval request.

    Args:
        approval_id: UUID of the approval request
        status: 'approved' | 'rejected' | 'escalated'
        reviewer: Email or ID of the human reviewer
        comments: Optional reviewer comments
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE approval_queue
            SET status = %s,
                reviewer = %s,
                reviewer_comments = %s,
                reviewed_at = now()
            WHERE id = %s
            """,
            (status, reviewer, comments, approval_id)
        )


# ── Audit Log ────────────────────────────────────────────────

def log_audit_event(
    conn,
    workflow_id: str,
    event_type: str,
    event_data: dict,
    actor: str = "system"
):
    """
    Write an immutable audit log entry.
    Called automatically by all other functions — you rarely need to call this directly.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (workflow_id, event_type, event_data, actor)
            VALUES (%s, %s, %s, %s)
            """,
            (workflow_id, event_type, Json(event_data), actor)
        )


def get_workflow_audit_trail(conn, workflow_id: str) -> list:
    """
    Retrieve the complete, ordered audit trail for a workflow.
    Returns list of (event_type, event_data, actor, timestamp) tuples.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT event_type, event_data, actor, timestamp
            FROM audit_log
            WHERE workflow_id = %s
            ORDER BY timestamp ASC
            """,
            (workflow_id,)
        )
        return cur.fetchall()


def get_pending_approvals(conn) -> list:
    """
    Fetch all approvals awaiting human review.
    Useful for building approval dashboards.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT aq.id, aw.workflow_name, aq.recommendation, aq.created_at
            FROM approval_queue aq
            JOIN agent_workflows aw ON aq.workflow_id = aw.id
            WHERE aq.status = 'pending'
            ORDER BY aq.created_at ASC
        """)
        return cur.fetchall()

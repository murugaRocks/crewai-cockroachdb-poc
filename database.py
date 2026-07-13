"""
database.py
-----------
CockroachDB connection and data access layer for the CrewAI PoC.

This module handles:
  - Connection management
  - Schema initialization (tables + ENUM types)
  - Serialization-failure retry loop (CockroachDB SQLSTATE 40001)
  - Workflow lifecycle (create, update, complete)
  - Agent action persistence
  - Human-in-the-loop approval queue
  - Immutable audit logging
"""

import os
import time
import psycopg2
from psycopg2.extras import Json
from psycopg2.errors import SerializationFailure
from dotenv import load_dotenv

load_dotenv()


# Connection

def get_connection():
    """
    Create and return a connection to CockroachDB.
    Reads COCKROACHDB_URL from the environment.

    Note: autocommit is left OFF so that multi-statement writes
    (main insert + audit event) run atomically inside `_run_transaction`.
    """
    connection_string = os.getenv("COCKROACHDB_URL")
    if not connection_string:
        raise ValueError(
            "COCKROACHDB_URL environment variable is not set.\n"
            "Add it to your .env file:\n"
            "  COCKROACHDB_URL=postgresql://user:pass@host:26257/defaultdb?sslmode=verify-full"
        )
    conn = psycopg2.connect(connection_string)
    conn.autocommit = False
    return conn


# Transaction Retry Helper
#
# CockroachDB uses SERIALIZABLE isolation. Under contention it aborts
# transactions with SQLSTATE 40001 (serialization_failure) and expects
# the client to retry. This helper wraps a callable that receives a
# cursor and runs it inside an explicit transaction with exponential
# backoff on 40001.
#
# See: https://www.cockroachlabs.com/docs/stable/transaction-retry-error-reference

MAX_RETRIES = 3
RETRY_BASE_DELAY = 0.1  # seconds


def _run_transaction(conn, op, max_retries: int = MAX_RETRIES):
    """
    Execute `op(cursor)` inside a transaction, retrying on 40001.

    Args:
        conn: psycopg2 connection (autocommit must be False).
        op:   callable taking a cursor, returning any value.
        max_retries: number of retries after the first attempt.

    Returns whatever `op` returns.
    """
    for attempt in range(max_retries + 1):
        try:
            with conn.cursor() as cur:
                result = op(cur)
            conn.commit()
            return result
        except SerializationFailure:
            conn.rollback()
            if attempt == max_retries:
                raise
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
        except Exception:
            conn.rollback()
            raise


# Schema Initialization

def init_db(conn):
    """
    Create ENUM types and tables if they don't already exist.
    Safe to call on every startup (idempotent).
    """
    def _init(cur):
        cur.execute("""
            CREATE TYPE IF NOT EXISTS workflow_status AS ENUM (
                'pending', 'running', 'completed', 'failed'
            )
        """)
        cur.execute("""
            CREATE TYPE IF NOT EXISTS action_status AS ENUM (
                'pending', 'running', 'completed', 'failed'
            )
        """)
        cur.execute("""
            CREATE TYPE IF NOT EXISTS approval_status AS ENUM (
                'pending', 'approved', 'rejected', 'escalated'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_workflows (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_name STRING NOT NULL,
                status workflow_status NOT NULL DEFAULT 'pending',
                input_data JSONB,
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                INDEX idx_workflow_status (status),
                INDEX idx_workflow_name (workflow_name)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS agent_actions (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID NOT NULL REFERENCES agent_workflows(id) ON DELETE CASCADE,
                agent_name STRING NOT NULL,
                task_name STRING NOT NULL,
                input_data JSONB,
                output_data TEXT,
                status action_status NOT NULL DEFAULT 'pending',
                started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                completed_at TIMESTAMPTZ,
                INDEX idx_action_workflow (workflow_id),
                INDEX idx_action_agent (agent_name)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS approval_queue (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID NOT NULL REFERENCES agent_workflows(id) ON DELETE CASCADE,
                action_id   UUID NOT NULL REFERENCES agent_actions(id)   ON DELETE CASCADE,
                recommendation TEXT NOT NULL,
                status approval_status NOT NULL DEFAULT 'pending',
                reviewer STRING,
                reviewer_comments TEXT,
                reviewed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                INDEX idx_approval_status (status),
                INDEX idx_approval_workflow (workflow_id)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                workflow_id UUID,
                event_type STRING NOT NULL,
                event_data JSONB,
                actor STRING NOT NULL DEFAULT 'system',
                timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
                INDEX idx_audit_workflow (workflow_id),
                INDEX idx_audit_event_type (event_type),
                INDEX idx_audit_timestamp (timestamp)
            )
        """)

    _run_transaction(conn, _init)
    print("CockroachDB schema initialized successfully")


# Internal: audit-event insert helper (used inside a caller's transaction).

def _insert_audit_event(
    cur,
    workflow_id,
    event_type: str,
    event_data: dict,
    actor: str = "system",
):
    cur.execute(
        """
        INSERT INTO audit_log (workflow_id, event_type, event_data, actor)
        VALUES (%s, %s, %s, %s)
        """,
        (workflow_id, event_type, Json(event_data), actor),
    )


# Workflow Lifecycle

def create_workflow(conn, workflow_name: str, input_data: dict) -> str:
    """
    Insert a new workflow record and its WORKFLOW_STARTED audit event
    atomically, and return the workflow UUID.
    """
    def _op(cur):
        cur.execute(
            """
            INSERT INTO agent_workflows (workflow_name, input_data, status)
            VALUES (%s, %s, 'running')
            RETURNING id
            """,
            (workflow_name, Json(input_data)),
        )
        workflow_id = str(cur.fetchone()[0])
        _insert_audit_event(cur, workflow_id, "WORKFLOW_STARTED", {
            "workflow_name": workflow_name,
            "input_summary": str(input_data)[:500],
        })
        return workflow_id

    return _run_transaction(conn, _op)


def complete_workflow(conn, workflow_id: str, status: str = "completed"):
    """
    Mark a workflow as complete (or failed) and record the audit event
    atomically. Updates the completed_at timestamp.
    """
    def _op(cur):
        cur.execute(
            """
            UPDATE agent_workflows
            SET status = %s, completed_at = now()
            WHERE id = %s
            """,
            (status, workflow_id),
        )
        _insert_audit_event(cur, workflow_id, "WORKFLOW_COMPLETED", {
            "final_status": status,
        })

    _run_transaction(conn, _op)


# Agent Actions

def save_agent_action(
    conn,
    workflow_id: str,
    agent_name: str,
    task_name: str,
    input_data: dict,
    output: str,
) -> str:
    """
    Persist an agent's completed task output plus its audit event
    atomically. Returns the action UUID.
    """
    def _op(cur):
        cur.execute(
            """
            INSERT INTO agent_actions
                (workflow_id, agent_name, task_name, input_data, output_data, status, completed_at)
            VALUES (%s, %s, %s, %s, %s, 'completed', now())
            RETURNING id
            """,
            (workflow_id, agent_name, task_name, Json(input_data), output),
        )
        action_id = str(cur.fetchone()[0])
        _insert_audit_event(cur, workflow_id, "AGENT_ACTION_COMPLETED", {
            "agent": agent_name,
            "task": task_name,
            "output_preview": output[:300] if output else "",
        })
        return action_id

    return _run_transaction(conn, _op)


# Human-in-the-Loop

def create_approval_request(
    conn,
    workflow_id: str,
    action_id: str,
    recommendation: str,
) -> str:
    """
    Queue an AI recommendation for human review, plus audit event,
    atomically. Returns the approval request UUID.
    """
    def _op(cur):
        cur.execute(
            """
            INSERT INTO approval_queue (workflow_id, action_id, recommendation, status)
            VALUES (%s, %s, %s, 'pending')
            RETURNING id
            """,
            (workflow_id, action_id, recommendation),
        )
        approval_id = str(cur.fetchone()[0])
        _insert_audit_event(cur, workflow_id, "APPROVAL_REQUESTED", {
            "approval_id": approval_id,
            "recommendation_preview": recommendation[:300],
        })
        return approval_id

    return _run_transaction(conn, _op)


def process_approval(
    conn,
    approval_id: str,
    status: str,
    reviewer: str,
    comments: str = "",
):
    """
    Record a human reviewer's decision on an approval request, plus
    audit event, atomically.

    Args:
        approval_id: UUID of the approval request
        status: 'approved' | 'rejected' | 'escalated'
        reviewer: Email or ID of the human reviewer
        comments: Optional reviewer comments
    """
    def _op(cur):
        cur.execute(
            """
            UPDATE approval_queue
            SET status = %s,
                reviewer = %s,
                reviewer_comments = %s,
                reviewed_at = now()
            WHERE id = %s
            RETURNING workflow_id
            """,
            (status, reviewer, comments, approval_id),
        )
        row = cur.fetchone()
        workflow_id = str(row[0]) if row else None
        _insert_audit_event(cur, workflow_id, "APPROVAL_PROCESSED", {
            "approval_id": approval_id,
            "status": status,
            "reviewer": reviewer,
        }, actor=reviewer)

    _run_transaction(conn, _op)


# Audit Log

def log_audit_event(
    conn,
    workflow_id: str,
    event_type: str,
    event_data: dict,
    actor: str = "system",
):
    """
    Write a standalone audit log entry in its own transaction.

    Prefer inlining audit events into the transaction that produced them
    (see the `_insert_audit_event` helper); this function is for events
    that have no accompanying business write.
    """
    def _op(cur):
        _insert_audit_event(cur, workflow_id, event_type, event_data, actor)

    _run_transaction(conn, _op)


def get_workflow_audit_trail(conn, workflow_id: str) -> list:
    """
    Retrieve the complete, ordered audit trail for a workflow.
    Returns list of (event_type, event_data, actor, timestamp) tuples.
    """
    def _op(cur):
        cur.execute(
            """
            SELECT event_type, event_data, actor, timestamp
            FROM audit_log
            WHERE workflow_id = %s
            ORDER BY timestamp ASC
            """,
            (workflow_id,),
        )
        return cur.fetchall()

    return _run_transaction(conn, _op)


def get_pending_approvals(conn) -> list:
    """
    Fetch all approvals awaiting human review.
    Useful for building approval dashboards.
    """
    def _op(cur):
        cur.execute("""
            SELECT aq.id, aw.workflow_name, aq.recommendation, aq.created_at
            FROM approval_queue aq
            JOIN agent_workflows aw ON aq.workflow_id = aw.id
            WHERE aq.status = 'pending'
            ORDER BY aq.created_at ASC
        """)
        return cur.fetchall()

    return _run_transaction(conn, _op)

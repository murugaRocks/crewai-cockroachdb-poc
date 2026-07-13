"""
crdb_features.py
----------------
CockroachDB features that make this PoC more than a Postgres-with-a-logo.

Every function below is either impossible or considerably more work on
vanilla PostgreSQL. The idea is to give the "CockroachDB solves
operationalization" pitch something concrete to point at.

Features shown:
  1. AS OF SYSTEM TIME   — point-in-time audit reads without snapshots
  2. Follower Reads      — cheap globally-consistent reads for dashboards
  3. SPLIT AT            — pre-split hot ranges to avoid write hotspots
  4. SHOW RANGES         — see how the audit table is distributed
  5. Changefeed          — stream approval events to Kafka/webhook/S3

Usage (from a Python REPL):

    from database import get_connection
    from crdb_features import (
        read_workflow_at, read_recent_workflow_history,
        follower_read_pending_approvals, presplit_workflows,
        show_workflow_ranges, create_approval_changefeed,
    )
    conn = get_connection()
    # e.g. what did the audit trail look like 5 minutes ago?
    rows = read_workflow_at(conn, wf_id, "-5m")
"""

from __future__ import annotations

from typing import Iterable


# 1. AS OF SYSTEM TIME
#
# Postgres has no equivalent. To get "what did the audit log say 5
# minutes ago" you'd need pg_dump snapshots, logical decoding into a
# separate history table, or a temporal-table extension.
#
# CockroachDB stores MVCC versions natively and lets any read specify
# a past timestamp within the GC window (default 25h, configurable per
# zone). This is how you serve compliance queries like "show me the
# workflow state at the moment the incident occurred" without building
# a shadow history system.

def read_workflow_at(conn, workflow_id: str, when: str = "-30s") -> list:
    """
    Read the full audit trail for a workflow AS OF a past timestamp.

    Args:
        workflow_id: UUID string.
        when: `AS OF SYSTEM TIME` argument. Common values:
              "-30s" (30 seconds ago), "-5m", "-1h",
              "'2026-06-13 14:00:00+00:00'" (absolute).
              Must be within the GC window (default 25h).

    Returns list of (event_type, event_data, actor, timestamp) rows,
    reflecting the DB state at that historical point.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT event_type, event_data, actor, timestamp
            FROM audit_log
            AS OF SYSTEM TIME '{when}'
            WHERE workflow_id = %s
            ORDER BY timestamp ASC
            """,
            (workflow_id,),
        )
        return cur.fetchall()


def read_recent_workflow_history(
    conn,
    workflow_id: str,
    steps: Iterable[str] = ("-60s", "-30s", "-10s", "-1s"),
) -> dict:
    """
    Replay the workflow's audit trail at several past instants so you
    can inspect exactly when each event became visible.

    Returns a dict keyed by the `AS OF SYSTEM TIME` offset, whose value
    is the list of rows the DB would have returned at that time.
    """
    return {step: read_workflow_at(conn, workflow_id, step) for step in steps}


# 2. Follower Reads
#
# Postgres has read replicas but they're either async-lagged (streaming
# replication) or a separate serving path (logical replication into a
# read-only mirror). Neither gives you a consistent read at a bounded
# past timestamp routed to the nearest replica.
#
# CockroachDB's `follower_read_timestamp()` returns a timestamp far
# enough in the past that any replica can serve the read locally
# (typically ~4.8 seconds). For dashboards and audit reads this is
# often 10x cheaper and lower-latency than routing to the leaseholder.

def follower_read_pending_approvals(conn) -> list:
    """
    Fetch the pending-approvals list from the nearest replica using a
    follower read. Ideal for dashboards where a few seconds of staleness
    is fine.

    CockroachDB does not accept a per-table `AS OF SYSTEM TIME` clause
    inside a JOIN, so the read runs in an explicit read-only transaction
    whose timestamp is pinned via `BEGIN TRANSACTION AS OF SYSTEM TIME
    follower_read_timestamp()`. Any replica that holds the range can
    serve it, without a round-trip to the leaseholder.
    """
    # We want to send BEGIN / COMMIT literally, so temporarily flip
    # autocommit ON to keep psycopg2 from wrapping our statements in
    # its own implicit transaction.
    prev_autocommit = conn.autocommit
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "BEGIN TRANSACTION AS OF SYSTEM TIME follower_read_timestamp()"
            )
            try:
                cur.execute("""
                    SELECT aq.id, aw.workflow_name, aq.recommendation, aq.created_at
                    FROM approval_queue aq
                    JOIN agent_workflows aw ON aq.workflow_id = aw.id
                    WHERE aq.status = 'pending'
                    ORDER BY aq.created_at ASC
                """)
                rows = cur.fetchall()
                cur.execute("COMMIT")
                return rows
            except Exception:
                cur.execute("ROLLBACK")
                raise
    finally:
        conn.autocommit = prev_autocommit


# 3. SPLIT AT
#
# When you're about to bulk-load or fan out writes across many
# workflow_ids, CockroachDB will lazily split the underlying range,
# which causes early write hotspots on the initial single range. Postgres
# has no equivalent because it isn't range-sharded.
#
# `ALTER TABLE ... SPLIT AT` tells CRDB to pre-split the table into
# N ranges at chosen keys BEFORE the load starts, so writes distribute
# across the cluster immediately.

def presplit_workflows(conn, num_splits: int = 8) -> None:
    """
    Pre-split `agent_workflows` into `num_splits` ranges along the
    UUID primary-key space. Use before a bulk backfill / load-test.

    The keys chosen are equally-spaced UUIDs. Since our PK is
    gen_random_uuid() (uniform), this maps to roughly uniform load.
    """
    if num_splits < 2:
        return

    # Generate num_splits-1 boundary UUIDs by scaling the u128 space.
    max_u128 = (1 << 128) - 1
    boundaries = [
        _u128_to_uuid((i * max_u128) // num_splits)
        for i in range(1, num_splits)
    ]

    with conn.cursor() as cur:
        for uuid_str in boundaries:
            # SPLIT AT VALUES is idempotent per-key; safe to re-run.
            cur.execute(
                "ALTER TABLE agent_workflows SPLIT AT VALUES (%s)",
                (uuid_str,),
            )


def _u128_to_uuid(n: int) -> str:
    h = f"{n:032x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


# 4. SHOW RANGES
#
# Prove the split worked (or diagnose hotspots). Not available on
# Postgres — the concept of a "range" doesn't exist.

def show_workflow_ranges(conn) -> list:
    """
    Return the current range distribution for `agent_workflows`.
    Each row includes start/end key, replica list, and lease holder.
    """
    with conn.cursor() as cur:
        cur.execute("SHOW RANGES FROM TABLE agent_workflows")
        return cur.fetchall()


# 5. Changefeed
#
# The strongest single differentiator for the "AI Governance" story.
#
# On Postgres you'd stand up Debezium + Kafka Connect + a schema
# registry to stream row changes downstream. On CockroachDB it's one
# statement. Every approval status transition can be streamed to Kafka,
# a webhook, S3, or Google Pub/Sub with exactly-once ordering per key.
#
# This is what turns "we persisted the approval" into "we published an
# immutable, ordered event that a downstream immutable-storage service
# (compliance data lake, SIEM, audit vault) can subscribe to and no
# operator with SQL access can tamper with retroactively".
#
# Enterprise license required for external sinks. Core sinks
# (experimental) can be used for demos.

def create_approval_changefeed(
    conn,
    sink_uri: str,
    resolved: str = "10s",
) -> None:
    """
    Start a changefeed on `approval_queue` that emits every row change
    to `sink_uri`.

    Args:
        sink_uri: e.g.
            "kafka://kafka-broker:9092?topic_name=crewai_approvals"
            "webhook-https://audit-vault.example.com/ingest"
            "gcpubsub://my-project?TOPIC_NAME=crewai_approvals"
            "external://compliance-s3"
        resolved: how often to emit resolved timestamps (checkpoint
                  markers downstream consumers use for ordering).

    Requires an enterprise-licensed cluster for non-experimental sinks.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            CREATE CHANGEFEED FOR TABLE approval_queue, agent_workflows
            INTO %s
            WITH updated, resolved = '{resolved}', envelope = 'wrapped'
            """,
            (sink_uri,),
        )


def list_active_changefeeds(conn) -> list:
    """
    Return currently-running changefeed jobs so you can prove the
    audit stream is live.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT job_id, description, status, created, high_water_timestamp
            FROM [SHOW CHANGEFEED JOBS]
            WHERE status IN ('running', 'paused')
            ORDER BY created DESC
        """)
        return cur.fetchall()

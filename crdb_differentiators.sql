-- ============================================================
-- CockroachDB features that back the joint pitch
-- ============================================================
-- Every block below is either impossible or considerably more work
-- on vanilla Postgres. Use these as talking points and demo scripts.
-- The Python equivalents live in crdb_features.py.
-- ============================================================


-- ── 1. AS OF SYSTEM TIME (point-in-time audit reads) ────────
--
-- What did the audit trail look like 5 minutes ago?
-- Postgres equivalent: pg_dump snapshot + restore into a scratch DB,
-- or a temporal-table extension + manual history tracking.
-- CockroachDB: one clause. Works within the GC window (default 25h).

SELECT event_type, actor, timestamp
FROM audit_log
AS OF SYSTEM TIME '-5m'
WHERE workflow_id = '<your-workflow-id>'
ORDER BY timestamp ASC;

-- Absolute timestamp form (compliance: "state at the moment of the incident")
SELECT *
FROM approval_queue
AS OF SYSTEM TIME '2026-06-13 14:00:00+00:00'
WHERE status = 'pending';

-- Widen the GC window on the audit_log if you need longer retention
-- (25h -> 30 days). Postgres has no direct equivalent.
ALTER TABLE audit_log CONFIGURE ZONE USING gc.ttlseconds = 2592000;


-- ── 2. Follower Reads (cheap, low-latency dashboard reads) ──
--
-- follower_read_timestamp() returns a timestamp just old enough
-- (~4.8s) that ANY replica can serve the read locally without
-- consulting the leaseholder. Ideal for approval dashboards.
--
-- Postgres has read replicas but they're either async-lagged
-- (streaming replication) or require a separate serving path.

-- AS OF SYSTEM TIME cannot appear per-table inside a JOIN. For a
-- multi-table follower read, pin the timestamp on the whole transaction:
BEGIN TRANSACTION AS OF SYSTEM TIME follower_read_timestamp();
SELECT aq.id, aw.workflow_name, aq.recommendation, aq.created_at
FROM approval_queue aq
JOIN agent_workflows aw ON aq.workflow_id = aw.id
WHERE aq.status = 'pending'
ORDER BY aq.created_at ASC;
COMMIT;


-- ── 3. SPLIT AT (pre-split hot ranges) ──────────────────────
--
-- Before bulk-loading N workflows or running a load test, pre-split
-- agent_workflows into K ranges along the UUID PK space so writes
-- distribute across the cluster from the first insert.
-- Postgres has no equivalent since it isn't range-sharded.

ALTER TABLE agent_workflows SPLIT AT VALUES
    ('20000000-0000-0000-0000-000000000000'),
    ('40000000-0000-0000-0000-000000000000'),
    ('60000000-0000-0000-0000-000000000000'),
    ('80000000-0000-0000-0000-000000000000'),
    ('a0000000-0000-0000-0000-000000000000'),
    ('c0000000-0000-0000-0000-000000000000'),
    ('e0000000-0000-0000-0000-000000000000');

-- Verify the split worked and see current leaseholder distribution.
SHOW RANGES FROM TABLE agent_workflows;

-- Pin ranges to specific regions if you're multi-region
-- (Postgres cannot: single-writer topology).
ALTER TABLE agent_workflows SCATTER;


-- ── 4. Changefeeds (governance stream to Kafka/webhook/S3) ──
--
-- The strongest single "CockroachDB, not Postgres" argument for the
-- AI governance story. Stream every approval decision to a
-- downstream immutable sink (audit vault, SIEM, compliance lake).
--
-- Postgres equivalent: Debezium + Kafka Connect + schema registry.
-- CockroachDB: one CREATE CHANGEFEED. Exactly-once ordering per key.

-- Kafka sink
CREATE CHANGEFEED FOR TABLE approval_queue, agent_workflows
INTO 'kafka://kafka-broker:9092?topic_name=crewai_approvals'
WITH updated, resolved = '10s', envelope = 'wrapped';

-- Webhook sink (great for a Slack/PagerDuty approval notification)
CREATE CHANGEFEED FOR TABLE approval_queue
INTO 'webhook-https://audit-vault.example.com/ingest'
WITH updated, resolved = '10s';

-- Google Pub/Sub sink
CREATE CHANGEFEED FOR TABLE approval_queue
INTO 'gcpubsub://my-project?TOPIC_NAME=crewai_approvals'
WITH updated, resolved = '10s';

-- List running feeds so you can prove the audit stream is live
SELECT job_id, description, status, high_water_timestamp
FROM [SHOW CHANGEFEED JOBS]
WHERE status IN ('running', 'paused');


-- ── 5. Enforcing immutability on the audit log ──────────────
--
-- Turn the "immutable audit log" claim into an actual database-level
-- guarantee: revoke UPDATE/DELETE from every role except a break-glass
-- role. Combined with the changefeed above, no application user can
-- mutate history without leaving a trace in the downstream sink.

CREATE ROLE IF NOT EXISTS app_writer;
CREATE ROLE IF NOT EXISTS auditor_readonly;

GRANT INSERT, SELECT ON audit_log TO app_writer;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM app_writer;

GRANT SELECT ON audit_log TO auditor_readonly;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit_log FROM auditor_readonly;


-- ── 6. Multi-region topology (for the "Global Agent" pitch) ─
--
-- If the crew is deployed globally, put each region's row-set close
-- to its writers with REGIONAL BY ROW. Reads and writes for a
-- claim stay in-region. Postgres would need application-level sharding.

ALTER DATABASE defaultdb PRIMARY REGION 'us-east-1';
ALTER DATABASE defaultdb ADD REGION 'eu-west-1';
ALTER DATABASE defaultdb ADD REGION 'ap-southeast-1';

ALTER TABLE agent_workflows SET LOCALITY REGIONAL BY ROW;
ALTER TABLE agent_actions   SET LOCALITY REGIONAL BY ROW;
ALTER TABLE approval_queue  SET LOCALITY REGIONAL BY ROW;

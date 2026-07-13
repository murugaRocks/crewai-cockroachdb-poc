"""
main.py
-------
Entry point for the CrewAI + CockroachDB Insurance Claims PoC.

This script demonstrates all 7 joint sales angles:
  1. Agent State Persistence    — every agent output stored in CockroachDB
  2. Human-in-the-Loop          — AI recommends, human approves, then execution continues
  3. Multi-Agent Collaboration  — agents share context via CrewAI task chaining
  4. Enterprise Reliability     — CockroachDB HA, replication, strong consistency
  5. Global Agent Deployments   — CockroachDB distributed architecture
  6. AI Governance              — full immutable audit log in CockroachDB
  7. AI as Business Process     — end-to-end workflow from intake to approval

Usage:
    python main.py

Requirements:
    .env file with OPENAI_API_KEY and COCKROACHDB_URL
    See .env.example for the full template.
"""

import os
import time
from dotenv import load_dotenv
from crewai import Crew, Process

from agents import create_all_agents
from tasks import create_tasks
from database import (
    get_connection,
    init_db,
    create_workflow,
    save_agent_action,
    create_approval_request,
    process_approval,
    complete_workflow,
    get_workflow_audit_trail
)

load_dotenv()


# ── Sample Claim (PoC Demo Data) ─────────────────────────────
# In production, this would come from a claims intake API or CRM.

SAMPLE_CLAIM = {
    "claim_id": "CLM-2024-00123",
    "policy_number": "POL-AUTO-789456",
    "claimant_name": "Jane Doe",
    "claim_type": "Auto Collision",
    "claimed_amount": 18500,
    "incident_date": "2024-12-20",
    "description": (
        "Two-vehicle collision at the intersection of Main St and 5th Ave. "
        "Claimant states the other driver ran a red light. Police report filed "
        "at scene. Claimant visited ER same day for whiplash treatment."
    ),
    "documents": [
        "Police Report #2024-45678",
        "Photos (12 images)",
        "Repair Estimate — AutoShop Pro ($16,200)",
        "ER Visit Summary — City General Hospital",
        "Witness Statement — John Williams"
    ]
}


def print_header(text: str):
    """Print a formatted section header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print('='*60)


def print_step(icon: str, text: str):
    """Print a formatted step."""
    print(f"\n{icon} {text}")


def run_poc():
    """
    Main PoC execution function.
    Runs a full CrewAI workflow and persists every step to CockroachDB.
    """
    print_header("CrewAI + CockroachDB Insurance Claims PoC")
    print(f"  Claim: {SAMPLE_CLAIM['claim_id']} | ${SAMPLE_CLAIM['claimed_amount']:,}")
    print(f"  Claimant: {SAMPLE_CLAIM['claimant_name']}")
    print(f"  Type: {SAMPLE_CLAIM['claim_type']}")

    # ── Step 1: Connect to CockroachDB ───────────────────────
    print_step("📦", "Connecting to CockroachDB...")
    conn = get_connection()
    init_db(conn)

    workflow_id = None
    final_result = None
    try:
        # ── Step 2: Create workflow record ───────────────────
        print_step("📝", f"Creating workflow record for claim: {SAMPLE_CLAIM['claim_id']}")
        workflow_id = create_workflow(conn, "insurance_claims_processing", SAMPLE_CLAIM)
        print(f"   → Workflow ID: {workflow_id}")
        print(f"   → Status: RUNNING (persisted in CockroachDB)")

        # ── Step 3: Initialize agents ────────────────────────
        print_step("🤖", "Initializing CrewAI Agents...")
        agents = create_all_agents()
        print("   → Research Analyst Agent")
        print("   → Fraud Risk Specialist Agent")
        print("   → Recommendation Officer Agent")

        # ── Step 4: Define tasks ─────────────────────────────
        tasks = create_tasks(agents, SAMPLE_CLAIM)

        # ── Step 5: Run the crew (sequential pipeline) ───────
        print_step("🔄", "Running CrewAI sequential workflow...")
        print("-" * 60)

        crew = Crew(
            agents=list(agents.values()),
            tasks=tasks,
            process=Process.sequential,
            verbose=True
        )

        final_result = crew.kickoff()

        print("-" * 60)
        print_step("✅", "CrewAI workflow complete!")

        # ── Step 6: Persist all agent outputs to CockroachDB ─
        print_step("💾", "Persisting agent outputs to CockroachDB...")

        # CrewAI Task.output is a TaskOutput object whose `.raw` attribute
        # holds the agent's raw text. Fall back through common shapes.
        def _extract(task, fallback: str) -> str:
            out = getattr(task, "output", None)
            if out is None:
                return fallback
            for attr in ("raw", "raw_output"):
                val = getattr(out, attr, None)
                if val:
                    return str(val)
            return str(out)

        research_output = _extract(tasks[0], "Research analysis completed")
        risk_output = _extract(tasks[1], "Risk assessment completed")
        recommendation_output = _extract(tasks[2], str(final_result))

        research_action_id = save_agent_action(
            conn, workflow_id,
            "Insurance Claims Research Analyst",
            "claim_research_analysis",
            SAMPLE_CLAIM,
            research_output
        )
        print(f"   → Research output saved (ID: {research_action_id[:8]}...)")

        risk_action_id = save_agent_action(
            conn, workflow_id,
            "Fraud Risk Assessment Specialist",
            "fraud_risk_assessment",
            SAMPLE_CLAIM,
            risk_output
        )
        print(f"   → Risk assessment saved (ID: {risk_action_id[:8]}...)")

        recommendation_action_id = save_agent_action(
            conn, workflow_id,
            "Claims Decision Recommendation Officer",
            "final_recommendation",
            SAMPLE_CLAIM,
            recommendation_output
        )
        print(f"   → Recommendation saved (ID: {recommendation_action_id[:8]}...)")

        # ── Step 7: Human-in-the-Loop approval ───────────────
        print_step("👤", "Routing recommendation to Human-in-the-Loop approval queue...")
        approval_id = create_approval_request(
            conn, workflow_id, recommendation_action_id,
            recommendation_output
        )
        print(f"   → Approval Request ID: {approval_id}")
        print(f"   → Status: PENDING HUMAN REVIEW")
        print(f"   → In production: notification sent to claims supervisor")

        # Simulate human review delay
        print("\n⏳ Simulating human review (2 seconds)...")
        time.sleep(2)

        # Simulate human decision
        process_approval(
            conn, approval_id,
            status="approved",
            reviewer="supervisor@insurance-co.com",
            comments="AI recommendation reviewed. Documentation verified. Approved for settlement."
        )
        print_step("✅", "Human approval decision recorded in CockroachDB")
        print("   → Reviewer: supervisor@insurance-co.com")
        print("   → Decision: APPROVED")

        # ── Step 8: Complete workflow ────────────────────────
        complete_workflow(conn, workflow_id, status="completed")
        print_step("🏁", "Workflow marked as COMPLETED in CockroachDB")

        # ── Step 9: Display full audit trail ─────────────────
        print_step("📋", "Full Audit Trail (queried directly from CockroachDB):")
        print("-" * 60)
        audit_trail = get_workflow_audit_trail(conn, workflow_id)
        for event_type, event_data, actor, timestamp in audit_trail:
            print(f"  [{timestamp}]")
            print(f"    Event:  {event_type}")
            print(f"    Actor:  {actor}")
            print()

        # ── Final Summary ────────────────────────────────────
        print_header("PoC Summary")
        print(f"  ✅ Claim:       {SAMPLE_CLAIM['claim_id']}")
        print(f"  ✅ Workflow ID: {workflow_id}")
        print(f"  ✅ Approval ID: {approval_id}")
        print(f"  ✅ Audit Events: {len(audit_trail)} entries in CockroachDB")
        print()
        print("  What just happened:")
        print("  1. CrewAI ran 3 agents sequentially (Research → Risk → Recommendation)")
        print("  2. Every output was persisted to CockroachDB in real-time")
        print("  3. A human approval request was created and recorded")
        print("  4. Human approval was stored with reviewer identity and timestamp")
        print("  5. A full, immutable audit trail was written to CockroachDB")
        print()
        print("  This is CrewAI + CockroachDB: AI that's trustworthy, auditable,")
        print("  and production-ready. Not just a demo, a business process.")
        print('='*60)

        return final_result

    except Exception as exc:
        # Any failure between workflow-create and workflow-complete leaves the
        # row stuck at 'running'. Mark it failed so the audit trail reflects
        # reality, then re-raise so the caller sees the original traceback.
        if workflow_id is not None:
            try:
                complete_workflow(conn, workflow_id, status="failed")
                print_step("❌", f"Workflow failed: {exc!r}")
                print(f"   → Workflow {workflow_id} marked as FAILED in CockroachDB")
            except Exception as cleanup_exc:
                print_step("⚠️", f"Also failed to mark workflow FAILED: {cleanup_exc!r}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    run_poc()

"""
tasks.py
--------
CrewAI task definitions for the Insurance Claims Processing PoC.

Task flow (sequential):
  1. Research Task       → Research Agent analyzes the claim
  2. Risk Task           → Risk Agent evaluates fraud indicators (uses research output)
  3. Recommendation Task → Recommendation Agent produces the final recommendation
                           (uses both research and risk outputs)

Each task output is captured and persisted to CockroachDB in main.py.
"""

from crewai import Task


def create_tasks(agents: dict, claim_data: dict) -> list:
    """
    Create and return the ordered list of tasks for the claims processing workflow.

    Args:
        agents: Dict of instantiated agents (from agents.create_all_agents())
        claim_data: Dictionary containing the insurance claim details

    Returns:
        List of Task objects in execution order
    """

    # Format claim details for task prompts
    claim_summary = f"""
    Claim ID:          {claim_data.get('claim_id', 'N/A')}
    Policy Number:     {claim_data.get('policy_number', 'N/A')}
    Claimant:          {claim_data.get('claimant_name', 'N/A')}
    Claim Type:        {claim_data.get('claim_type', 'N/A')}
    Claimed Amount:    ${claim_data.get('claimed_amount', 0):,.2f}
    Incident Date:     {claim_data.get('incident_date', 'N/A')}
    Description:       {claim_data.get('description', 'N/A')}
    Documents Submitted: {', '.join(claim_data.get('documents', []))}
    """

    # ── Task 1: Research Analysis ────────────────────────────
    research_task = Task(
        description=f"""
        Conduct a thorough analysis of the following insurance claim:

        {claim_summary}

        Your structured research report must cover:
        1. Documentation Review — evaluate all submitted documents for completeness and authenticity
        2. Policy Verification — confirm the claim type and amount fall within policy coverage
        3. Claim Legitimacy — assess whether the described incident is consistent and plausible
        4. Historical Comparison — compare against typical claims of this type
        5. Gaps & Inconsistencies — identify any missing information or red flags

        Be factual, structured, and objective.
        """,
        expected_output=(
            "A structured research report with five clearly labelled sections: "
            "(1) Documentation Review, (2) Policy Verification, (3) Claim Legitimacy Assessment, "
            "(4) Historical Comparison, (5) Identified Gaps & Inconsistencies. "
            "Each section should include specific findings and a brief conclusion."
        ),
        agent=agents["research"]
    )

    # ── Task 2: Fraud Risk Assessment ────────────────────────
    risk_task = Task(
        description=f"""
        Based on the research report and the original claim details below,
        conduct a comprehensive fraud risk assessment:

        {claim_summary}

        Your risk assessment must include:
        1. Fraud Probability Score — assign a score from 0 (no risk) to 100 (definite fraud)
        2. Key Risk Indicators — list specific factors contributing to the score
        3. Legitimacy Factors — list specific factors that support the claim's authenticity
        4. Pattern Matching — note any similarities to known fraud typologies
        5. Overall Risk Verdict — LOW / MEDIUM / HIGH / CRITICAL

        Be precise with your score. Justify every point.
        """,
        expected_output=(
            "A structured risk assessment report containing: "
            "(1) Fraud Probability Score (0-100) with justification, "
            "(2) Detailed list of risk indicators, "
            "(3) Legitimacy-supporting factors, "
            "(4) Pattern matching notes, "
            "(5) Overall risk verdict (LOW/MEDIUM/HIGH/CRITICAL) with rationale."
        ),
        agent=agents["risk"],
        context=[research_task]   # Receives research_task output automatically
    )

    # ── Task 3: Final Recommendation ─────────────────────────
    recommendation_task = Task(
        description=f"""
        Based on the research report and fraud risk assessment for the claim below,
        produce a final recommendation formatted for human reviewer approval:

        {claim_summary}

        Your recommendation must be structured as follows:
        1. DECISION — one of: APPROVE | PARTIAL APPROVE | DENY | ESCALATE TO SENIOR ADJUSTER
        2. Recommended Settlement Amount — exact dollar amount (if applicable)
        3. Decision Justification — clear, concise reasoning referencing specific findings
        4. Conditions or Required Next Steps — what must happen before payment is released
        5. Human Reviewer Summary — a brief (3-4 sentence) plain-English summary for the reviewer

        IMPORTANT: This recommendation will be stored in CockroachDB and routed to a human
        reviewer for mandatory approval. No payment or action will occur without human sign-off.
        Design your output for a human to review and approve within 60 seconds.
        """,
        expected_output=(
            "A structured recommendation document containing: "
            "(1) Clear DECISION in capital letters, "
            "(2) Settlement amount in USD, "
            "(3) Detailed justification, "
            "(4) Conditions/next steps, "
            "(5) A plain-English reviewer summary. "
            "The entire recommendation should be concise enough for a human to review in under 60 seconds."
        ),
        agent=agents["recommendation"],
        context=[research_task, risk_task]   # Receives both prior outputs
    )

    return [research_task, risk_task, recommendation_task]

"""
agents.py
---------
CrewAI agent definitions for the Insurance Claims Processing PoC.

Agents:
  1. Research Analyst     — Reviews claim documentation and verifies policy coverage
  2. Risk Specialist      — Evaluates fraud risk and produces a risk score
  3. Recommendation Officer — Synthesizes findings into a human-ready recommendation

Each agent's output is persisted to CockroachDB via database.py,
creating a full audit trail for governance and compliance.
"""

from crewai import Agent


def create_research_agent() -> Agent:
    """
    Research Analyst Agent.
    Analyzes claim documentation and verifies policy coverage.
    """
    return Agent(
        role="Insurance Claims Research Analyst",
        goal=(
            "Analyze insurance claims thoroughly by examining all submitted evidence, "
            "policy details, and historical data to provide a comprehensive assessment "
            "of claim validity and completeness."
        ),
        backstory=(
            "You are an expert insurance claims analyst with 15 years of experience. "
            "You specialize in reviewing claim documentation, identifying patterns, and "
            "assessing the validity and severity of claims. You are thorough, objective, "
            "and detail-oriented. You never make assumptions — you work only from evidence."
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=3
    )


def create_risk_agent() -> Agent:
    """
    Fraud Risk Assessment Agent.
    Evaluates claims for fraud indicators and produces a risk score (0-100).
    """
    return Agent(
        role="Fraud Risk Assessment Specialist",
        goal=(
            "Evaluate insurance claims for potential fraud indicators, assess risk scores "
            "on a 0-100 scale, and flag suspicious patterns using cross-referencing with "
            "known fraud typologies."
        ),
        backstory=(
            "You are a fraud detection specialist with deep expertise in insurance fraud "
            "patterns. You analyze claims for red flags, cross-reference with known fraud "
            "typologies, and produce detailed risk assessments with clear numerical scores. "
            "Your work balances skepticism with fairness — you flag genuine concerns without "
            "unfairly penalizing legitimate claimants."
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=3
    )


def create_recommendation_agent() -> Agent:
    """
    Claims Decision Recommendation Agent.
    Synthesizes research + risk findings into a structured recommendation for human review.
    """
    return Agent(
        role="Claims Decision Recommendation Officer",
        goal=(
            "Synthesize research findings and risk assessments to produce a clear, "
            "justified recommendation for claim approval, partial approval, denial, "
            "or escalation — formatted for human reviewer sign-off."
        ),
        backstory=(
            "You are a senior claims decision officer who synthesizes complex, multi-source "
            "analysis into clear, actionable recommendations. You balance business requirements, "
            "regulatory compliance, and customer fairness. Your recommendations are structured "
            "for human reviewers, including the decision, amount, justification, and next steps. "
            "You understand that a human will review and approve your recommendation before "
            "any action is taken — this is by design."
        ),
        verbose=True,
        allow_delegation=False,
        max_iter=3
    )


def create_all_agents() -> dict:
    """
    Instantiate all agents and return them as a named dictionary.

    Returns:
        dict with keys: 'research', 'risk', 'recommendation'
    """
    return {
        "research": create_research_agent(),
        "risk": create_risk_agent(),
        "recommendation": create_recommendation_agent()
    }

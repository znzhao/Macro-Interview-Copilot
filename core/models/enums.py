"""Controlled vocabularies. Single source of truth for the domain's fixed value sets.

Free-text drift here (e.g. "Monetary Policy" vs "monetary policy") silently fragments
topic_mastery rows and breaks weakness detection. See docs/DATA_SPEC.md #9.
"""

from __future__ import annotations

from enum import StrEnum


class QuestionTier(StrEnum):
    VERIFIED = "verified"
    COMMUNITY = "community"
    PRIVATE = "private"


class QuestionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    FLAGGED = "flagged"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class Frequency(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class VerificationLevel(StrEnum):
    VERIFIED_INTERVIEW = "verified_interview"
    MULTIPLE_INDEPENDENT_REPORTS = "multiple_independent_reports"
    OFFICIAL_PUBLICATION = "official_publication"
    OFFICIAL_JOB_MATERIAL = "official_job_material"
    SYNTHESIZED_FROM_OFFICIAL_TOPICS = "synthesized_from_official_topics"
    AI_GENERATED = "ai_generated"
    USER_SUBMITTED = "user_submitted"


class ExperienceLevel(StrEnum):
    ENTRY = "entry"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class SessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class InterviewerMode(StrEnum):
    HEDGE_FUND = "hedge_fund"
    CENTRAL_BANK = "central_bank"
    IFI = "ifi"
    SELL_SIDE = "sell_side"


class TargetRole(StrEnum):
    GLOBAL_MACRO_HF = "global_macro_hf"
    IMF_ECONOMIST = "imf_economist"
    CENTRAL_BANK_ECONOMIST = "central_bank_economist"
    SELL_SIDE_ECONOMIST = "sell_side_economist"
    FIXED_INCOME_RESEARCH = "fixed_income_research"
    FX_RESEARCH = "fx_research"
    SOVEREIGN_WEALTH_FUND = "sovereign_wealth_fund"


class ReportReason(StrEnum):
    INACCURATE = "inaccurate"
    NO_SOURCE = "no_source"
    DUPLICATE = "duplicate"
    OFFENSIVE = "offensive"
    OTHER = "other"


class ReportStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Module(StrEnum):
    MACRO_FRAMEWORK = "Macro Framework"
    BUSINESS_CYCLE = "Business Cycle"
    INFLATION = "Inflation"
    MONETARY_POLICY = "Monetary Policy"
    FISCAL_POLICY = "Fiscal Policy"
    RATES_YIELD_CURVE = "Rates & Yield Curve"
    FX = "FX"
    BALANCE_OF_PAYMENTS = "Balance of Payments & Capital Flows"
    CREDIT_BANKING = "Credit & Banking"
    FINANCIAL_STABILITY = "Financial Stability"
    SOVEREIGN_DEBT = "Sovereign Debt"
    EMERGING_MARKETS = "Emerging Markets"
    COMMODITIES = "Commodities"
    GLOBAL_LIQUIDITY = "Global Liquidity"
    COUNTRY_ANALYSIS = "Country Analysis"
    INVESTMENT_PROCESS = "Investment Process"
    DATA_FORECASTING = "Data & Forecasting"


# Module-scoped topic vocabulary. This is the single source of truth referenced by
# Question._topic_belongs_to_module and by scripts/validate_content.py.
TOPICS_BY_MODULE: dict[Module, tuple[str, ...]] = {
    Module.MACRO_FRAMEWORK: (
        "Framework Building",
        "Top-Down vs Bottom-Up",
        "Scenario Analysis",
        "Reflexivity",
    ),
    Module.BUSINESS_CYCLE: (
        "Cycle Dating",
        "Leading Indicators",
        "Output Gap",
        "Recession Risk",
        "Potential Growth",
    ),
    Module.INFLATION: (
        "Inflation Dynamics",
        "Core vs Headline",
        "Wage-Price Spiral",
        "Inflation Expectations",
        "Supply-Side Inflation",
    ),
    Module.MONETARY_POLICY: (
        "Policy Transmission",
        "Central Bank Reaction Function",
        "Forward Guidance",
        "Quantitative Easing",
        "Neutral Rate",
    ),
    Module.FISCAL_POLICY: (
        "Fiscal Multipliers",
        "Debt Sustainability",
        "Automatic Stabilizers",
        "Fiscal-Monetary Interaction",
    ),
    Module.RATES_YIELD_CURVE: (
        "Term Premium",
        "Curve Inversion",
        "Forward Rates",
        "Real Rates",
        "Rate Volatility",
    ),
    Module.FX: (
        "FX Framework",
        "Purchasing Power Parity",
        "Interest Rate Parity",
        "Carry Trade",
        "Currency Intervention",
    ),
    Module.BALANCE_OF_PAYMENTS: (
        "Current Account",
        "Capital Flows",
        "Twin Deficits",
        "External Vulnerability",
    ),
    Module.CREDIT_BANKING: (
        "Credit Cycle",
        "Bank Lending Channel",
        "Credit Spreads",
        "Shadow Banking",
    ),
    Module.FINANCIAL_STABILITY: (
        "Systemic Risk",
        "Leverage",
        "Liquidity Risk",
        "Macroprudential Policy",
    ),
    Module.SOVEREIGN_DEBT: (
        "Debt Dynamics",
        "Sovereign Default Risk",
        "Debt Restructuring",
        "Fiscal Space",
    ),
    Module.EMERGING_MARKETS: (
        "EM Vulnerability",
        "China Macro",
        "EM Currency Crises",
        "Commodity Exporters",
    ),
    Module.COMMODITIES: (
        "Oil Markets",
        "Commodity Supercycle",
        "Commodity-FX Linkage",
    ),
    Module.GLOBAL_LIQUIDITY: (
        "Global Liquidity Cycle",
        "Dollar Funding",
        "Cross-Border Flows",
    ),
    Module.COUNTRY_ANALYSIS: (
        "US Economy",
        "Europe",
        "Japan",
        "Country Case Study",
    ),
    Module.INVESTMENT_PROCESS: (
        "Trade Construction",
        "Risk Scenarios",
        "Cross-Asset Analysis",
        "Positioning",
    ),
    Module.DATA_FORECASTING: (
        "Data Interpretation",
        "Macro Forecasting",
        "Nowcasting",
    ),
}

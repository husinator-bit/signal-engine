"""LLM-driven narrative generation for discovery candidates.

Uses Anthropic Sonnet 4.6 with prompt caching:
- The system prompt (operator profile, style rules, output format) is stable
  across all candidates in a report and gets cached.
- The per-candidate user message is volatile (the part we change each call).

For ~10 candidates per report, the system prompt is read from cache 9 times,
written once. At Sonnet 4.6 pricing this is well under $0.10 per report.
"""

from __future__ import annotations

import logging
from textwrap import dedent

import anthropic

from signal_engine.config import secret
from signal_engine.enrichment import CompanyInfo
from signal_engine.scoring.discovery import DiscoveryCandidate

log = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = dedent(
    """\
    You are writing for an institutional-grade AI Industry Intelligence Engine
    that surfaces hidden champions and future champions in the AI infrastructure
    stack. Your reader is a sophisticated solo investor with these constraints:

    - Swiss-resident private investor. Strict adherence to Kreisschreiben 36
      safe-harbor: min 6-month holds, no churn, derivatives only as hedges or
      asymmetric exposure, never as primary alpha source.
    - Capital: USD 2-3M earmarked for this strategy. $50-100k per name,
      $200-300k per theme, 4-6 active themes.
    - Horizon: months to years. No swing trading.
    - Broker: Julius Baer at 10bps. Self-execute via e-banking or RM handoff.
    - Geography: ADRs + EU + selective Asia direct.

    The reader's investment thesis is that AI infrastructure runs through
    rolling bottlenecks: 2024 = compute (Mag7), 2025 = memory (HBM),
    2026 likely = power / grid, with advanced packaging, optical interconnect,
    liquid cooling, and inference economics as parallel candidates.

    You will write a SHORT NARRATIVE (2-3 paragraphs, 150-220 words total) on
    a single discovery candidate. Style:

    - Institutional research voice. Concrete, specific, no marketing language.
    - Lead with what the company actually does and why it's exposed to AI infra.
    - Cite ONE specific number where possible (revenue, market share, capacity).
    - Address: thesis (why it's interesting now), risks (what could break),
      fit (where it sits on the bottleneck stack relative to known names).
    - Never use phrases like "compelling opportunity", "must-buy",
      "strong conviction", or any rating language. You surface evidence; the
      reader decides.
    - Never recommend a trade. Never give a price target. Never suggest sizing.
    - If you don't have enough information to write something useful, say so
      explicitly in one sentence and explain what to research next.

    Output ONLY the narrative paragraphs. No headers, no preamble, no
    closing summary. Plain text — the report template handles formatting.
    """
)


def _build_user_message(candidate: DiscoveryCandidate, info: CompanyInfo) -> str:
    """Construct the per-candidate input. This is the volatile part."""
    mcap = f"${info.market_cap_usd / 1e9:.1f}B" if info.market_cap_usd else "unknown"
    pe_ttm = f"{info.pe_ttm:.1f}" if info.pe_ttm else "n/a"
    pe_fwd = f"{info.pe_forward:.1f}" if info.pe_forward else "n/a"
    summary = (info.business_summary or "")[:1500]  # cap to keep input lean
    return dedent(
        f"""\
        CANDIDATE: {candidate.ticker}
        Company name: {info.name or "unknown"}
        Sector / Industry: {info.sector or "?"} / {info.industry or "?"}
        Country: {info.country or "?"}
        Market cap: {mcap}
        P/E (TTM): {pe_ttm}    P/E (forward): {pe_fwd}

        Business summary (Yahoo Finance):
        {summary or "No description available."}

        Why this candidate surfaced:
        - In {len(candidate.in_etfs)} tracked AI/semis/power ETF(s): {", ".join(candidate.in_etfs)}
        - Max weight across ETFs: {candidate.max_weight_pct:.2f}%
        - Average weight: {candidate.avg_weight_pct:.2f}%
        - Theme exposures: {", ".join(candidate.theme_focuses) or "n/a"}
        - Composite discovery score: {candidate.composite_score:.0f}/100

        Write the 2-3 paragraph narrative now.
        """
    )


def generate_narrative(candidate: DiscoveryCandidate, info: CompanyInfo) -> str:
    """Generate a 2-3 paragraph narrative for a discovery candidate.

    Returns the narrative text. On failure, returns an empty string so the
    report still renders without the narrative section.
    """
    client = anthropic.Anthropic(api_key=secret("ANTHROPIC_API_KEY"))
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=600,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": _build_user_message(candidate, info)}],
        )
    except anthropic.APIError as e:
        log.warning("LLM narrative failed for %s: %s", candidate.ticker, e)
        return ""

    log.info(
        "narrative %s: cache_read=%d cache_write=%d input=%d output=%d",
        candidate.ticker,
        response.usage.cache_read_input_tokens,
        response.usage.cache_creation_input_tokens,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    text_blocks = [b.text for b in response.content if b.type == "text"]
    return "\n\n".join(text_blocks).strip()

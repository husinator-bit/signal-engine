"""Parse SEC Form 4 (insider transactions) XML on demand.

Form 4 XML structure (simplified):
  <ownershipDocument>
    <reportingOwner>
      <reportingOwnerId><rptOwnerName>...</rptOwnerName></reportingOwnerId>
      <reportingOwnerRelationship>
        <isDirector>1</isDirector>
        <isOfficer>1</isOfficer>
        <officerTitle>...</officerTitle>
      </reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
      <nonDerivativeTransaction>
        <transactionDate><value>...</value></transactionDate>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>...</value></transactionShares>
          <transactionPricePerShare><value>...</value></transactionPricePerShare>
          <transactionAcquiredDisposedCode><value>A or D</value></transactionAcquiredDisposedCode>
        </transactionAmounts>
      </nonDerivativeTransaction>
    </nonDerivativeTable>
  </ownershipDocument>

Transaction codes that matter:
  P = open-market purchase  (bullish signal)
  S = open-market sale      (potentially bearish)
  A = grant / award         (compensation, not directional)
  M = option exercise       (often followed by S)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date
from typing import Optional

import httpx
from defusedxml import ElementTree as ET

log = logging.getLogger(__name__)


@dataclass
class InsiderTxn:
    insider_name: str
    insider_role: str           # "Director", "Officer (CEO)", "10% Owner", etc.
    transaction_type: str       # "buy", "sell", "grant", "option_exercise", "other"
    code: str                   # raw SEC code: P, S, A, M, ...
    shares: float
    price_per_share: Optional[float]
    value_usd: Optional[float]
    transacted_at: date


_CODE_TO_TYPE = {
    "P": "buy",
    "S": "sell",
    "A": "grant",
    "M": "option_exercise",
    "F": "tax_withholding",
    "G": "gift",
    "D": "disposition",
}


def _role(rel: ET.Element) -> str:
    parts = []
    if (e := rel.find("isDirector")) is not None and (e.text or "").strip() in ("1", "true"):
        parts.append("Director")
    if (e := rel.find("isOfficer")) is not None and (e.text or "").strip() in ("1", "true"):
        title = rel.findtext("officerTitle", default="").strip()
        parts.append(f"Officer ({title})" if title else "Officer")
    if (e := rel.find("isTenPercentOwner")) is not None and (e.text or "").strip() in ("1", "true"):
        parts.append("10% Owner")
    if (e := rel.find("isOther")) is not None and (e.text or "").strip() in ("1", "true"):
        parts.append("Other")
    return ", ".join(parts) or "Insider"


def _val(parent: Optional[ET.Element], tag: str) -> Optional[str]:
    if parent is None:
        return None
    el = parent.find(tag)
    if el is None:
        return None
    v = el.find("value")
    return v.text if v is not None and v.text else None


def parse_form4(xml_bytes: bytes) -> list[InsiderTxn]:
    """Parse a Form 4 XML document. Returns list of insider transactions, one
    per non-derivative transaction. Derivative table (options) is ignored for v0."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.warning("Form 4 parse error: %s", e)
        return []

    # Owner
    owner_el = root.find("reportingOwner")
    if owner_el is None:
        return []
    name = (
        owner_el.findtext("reportingOwnerId/rptOwnerName", default="").strip() or "Unknown"
    )
    rel_el = owner_el.find("reportingOwnerRelationship")
    role = _role(rel_el) if rel_el is not None else "Insider"

    out: list[InsiderTxn] = []
    nd_table = root.find("nonDerivativeTable")
    if nd_table is None:
        return out
    for txn in nd_table.findall("nonDerivativeTransaction"):
        date_str = _val(txn, "transactionDate")
        code = _val(txn, "transactionCoding/transactionCode") or ""
        shares_str = _val(txn, "transactionAmounts/transactionShares")
        price_str = _val(txn, "transactionAmounts/transactionPricePerShare")
        ad = _val(txn, "transactionAmounts/transactionAcquiredDisposedCode") or ""
        if not (date_str and shares_str):
            continue
        try:
            txn_date = date.fromisoformat(date_str[:10])
            shares = float(shares_str)
        except (ValueError, TypeError):
            continue
        price: Optional[float] = None
        if price_str:
            try:
                price = float(price_str)
            except ValueError:
                pass

        ttype = _CODE_TO_TYPE.get(code.upper(), "other")
        # A 'P' is unambiguously a buy. Otherwise lean on Acquired/Disposed.
        if ttype == "other":
            ttype = "buy" if ad == "A" else "sell" if ad == "D" else "other"

        value_usd = shares * price if price is not None else None
        out.append(
            InsiderTxn(
                insider_name=name,
                insider_role=role,
                transaction_type=ttype,
                code=code,
                shares=shares,
                price_per_share=price,
                value_usd=value_usd,
                transacted_at=txn_date,
            )
        )
    return out


def _to_raw_xml_url(url: str) -> str:
    """SEC's primary_doc for Form 4 typically points at the XSL-transformed
    HTML view (path contains `/xslF345X06/`). Strip that segment to get the
    raw XML, which is at the same path without the xsl directory."""
    return url.replace("/xslF345X06/", "/").replace("/xslF345X05/", "/")


def fetch_and_parse(filing_url: str) -> list[InsiderTxn]:
    """Download a Form 4 primary XML and parse it. Returns [] on any failure."""
    email = os.environ.get("USER_EMAIL", "ops@example.com")
    headers = {"User-Agent": f"signal-engine ({email})", "Accept": "application/xml"}
    raw_url = _to_raw_xml_url(filing_url)
    try:
        with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as client:
            r = client.get(raw_url)
            r.raise_for_status()
            return parse_form4(r.content)
    except (httpx.HTTPError, httpx.RequestError) as e:
        log.warning("Form 4 fetch failed for %s: %s", raw_url, e)
        return []

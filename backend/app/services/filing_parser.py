"""Parse SEC filing HTML into structured sections.

10-K/10-Q items are standardized by SEC Regulation S-K, so we can reliably
detect section boundaries using regex patterns on Item headers.  Tables are
extracted and converted to markdown so they can be stored as separate chunks
that preserve their spatial structure.
"""

import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from markdownify import markdownify as md

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section definitions (SEC Regulation S-K / Form 8-K instructions)
# ---------------------------------------------------------------------------

SECTIONS_10K: dict[str, dict] = {
    "1":   {"name": "Item 1 - Business",                  "category": "business_overview"},
    "1A":  {"name": "Item 1A - Risk Factors",              "category": "risk_factors"},
    "1B":  {"name": "Item 1B - Unresolved Staff Comments",  "category": "regulatory"},
    "1C":  {"name": "Item 1C - Cybersecurity",              "category": "risk_factors"},
    "2":   {"name": "Item 2 - Properties",                  "category": "business_overview"},
    "3":   {"name": "Item 3 - Legal Proceedings",            "category": "legal"},
    "5":   {"name": "Item 5 - Market Information",           "category": "market_info"},
    "6":   {"name": "Item 6 - Selected Financial Data",      "category": "financial_data"},
    "7":   {"name": "Item 7 - MD&A",                         "category": "financial_discussion"},
    "7A":  {"name": "Item 7A - Market Risk Disclosures",     "category": "risk_factors"},
    "8":   {"name": "Item 8 - Financial Statements",         "category": "financial_statements"},
    "9":   {"name": "Item 9 - Accountant Disagreements",     "category": "regulatory"},
    "9A":  {"name": "Item 9A - Controls and Procedures",     "category": "regulatory"},
    "9B":  {"name": "Item 9B - Other Information",           "category": "regulatory"},
}

SECTIONS_10Q: dict[str, dict] = {
    "P1-1":  {"name": "Part I Item 1 - Financial Statements",  "category": "financial_statements"},
    "P1-2":  {"name": "Part I Item 2 - MD&A",                   "category": "financial_discussion"},
    "P1-3":  {"name": "Part I Item 3 - Market Risk",            "category": "risk_factors"},
    "P1-4":  {"name": "Part I Item 4 - Controls",               "category": "regulatory"},
    "P2-1":  {"name": "Part II Item 1 - Legal Proceedings",     "category": "legal"},
    "P2-1A": {"name": "Part II Item 1A - Risk Factors",         "category": "risk_factors"},
    "P2-2":  {"name": "Part II Item 2 - Equity Repurchases",    "category": "market_info"},
    "P2-6":  {"name": "Part II Item 6 - Exhibits",              "category": "regulatory"},
}

# 8-K items by item number prefix
SECTIONS_8K: dict[str, dict] = {
    "1.01": {"name": "Item 1.01 - Material Agreement",          "category": "events_transactions"},
    "1.02": {"name": "Item 1.02 - Termination of Agreement",    "category": "events_transactions"},
    "1.05": {"name": "Item 1.05 - Cybersecurity Incident",      "category": "risk_factors"},
    "2.01": {"name": "Item 2.01 - Acquisition/Disposition",     "category": "events_transactions"},
    "2.02": {"name": "Item 2.02 - Earnings Results",            "category": "financial_discussion"},
    "2.05": {"name": "Item 2.05 - Exit/Disposal Activities",    "category": "events_transactions"},
    "5.02": {"name": "Item 5.02 - Officer/Director Changes",    "category": "corporate_governance"},
    "5.03": {"name": "Item 5.03 - Bylaws Amendment",            "category": "corporate_governance"},
    "7.01": {"name": "Item 7.01 - Reg FD Disclosure",           "category": "guidance_outlook"},
    "8.01": {"name": "Item 8.01 - Other Events",                "category": "guidance_outlook"},
    "9.01": {"name": "Item 9.01 - Exhibits",                    "category": "regulatory"},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ParsedSection:
    section_id: str
    section_name: str
    category: str
    text_content: str
    tables: list[str] = field(default_factory=list)
    token_count: int = 0


@dataclass
class ParsedFiling:
    filing_type: str
    sections: list[ParsedSection] = field(default_factory=list)
    raw_text_fallback: str = ""
    parse_quality: str = "sectioned"  # "sectioned" | "fallback"


# ---------------------------------------------------------------------------
# Regex for detecting section boundaries
# ---------------------------------------------------------------------------

# Matches "Item 1A", "ITEM 7", "Item 2.02", etc.  Captures the item number.
# Requires word boundary before and punctuation/whitespace after to avoid
# matching inside sentences or TOC hyperlinks.
_ITEM_PATTERN = re.compile(
    r"(?:^|\n)\s*(?:ITEM|Item)\s+(\d+(?:[A-Ca-c])?(?:\.\d{2})?)\s*[\.\:\-\—\s]",
    re.MULTILINE,
)

# TOC anchor pattern — matches when an item header is inside a link
_TOC_LINK_PATTERN = re.compile(r"<a\b[^>]*>.*?(?:ITEM|Item)\s+\d", re.IGNORECASE | re.DOTALL)

# Table placeholder used during parsing so tables aren't mixed into text flow
_TABLE_PLACEHOLDER = "\n[[TABLE_PLACEHOLDER_{idx}]]\n"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_filing_html(html: str, filing_type: str) -> ParsedFiling:
    """Parse SEC filing HTML into structured sections with extracted tables.

    Args:
        html: Raw HTML of the filing document.
        filing_type: "10-K", "10-Q", or "8-K".

    Returns:
        ParsedFiling with sections (or fallback to full text if detection fails).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Step 1: Extract tables as markdown, replace in DOM with placeholders
    tables_md = _extract_tables_as_markdown(soup)

    # Step 2: Convert remaining HTML to clean text
    clean_text = _clean_html_to_text(soup)

    # Step 3: Detect section boundaries
    section_map = _get_section_map(filing_type)
    sections = _detect_sections(clean_text, filing_type, section_map, tables_md)

    if len(sections) >= 2:
        logger.info(
            f"Parsed {filing_type}: {len(sections)} sections detected "
            f"({', '.join(s.section_id for s in sections)})"
        )
        return ParsedFiling(
            filing_type=filing_type,
            sections=sections,
            parse_quality="sectioned",
        )

    # Fallback: treat entire text as one section
    logger.warning(
        f"Section detection failed for {filing_type} "
        f"(found {len(sections)} sections), using fallback"
    )
    fallback_section = ParsedSection(
        section_id="full_document",
        section_name="Full Document",
        category="general",
        text_content=clean_text,
        tables=[t for t in tables_md.values()],
    )
    return ParsedFiling(
        filing_type=filing_type,
        sections=[fallback_section],
        raw_text_fallback=clean_text,
        parse_quality="fallback",
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_tables_as_markdown(soup: BeautifulSoup) -> dict[int, str]:
    """Extract all HTML tables, convert to markdown, replace with placeholders.

    Returns dict mapping placeholder index -> markdown table text.
    Modifies the soup in place (replaces <table> with placeholder text).
    """
    tables_md: dict[int, str] = {}
    for idx, table in enumerate(soup.find_all("table")):
        try:
            table_html = str(table)
            markdown = md(table_html, strip=["img", "a"]).strip()
            # Skip tiny tables (likely layout/navigation, not data)
            if len(markdown) < 30:
                table.decompose()
                continue
            tables_md[idx] = markdown
            placeholder = soup.new_string(_TABLE_PLACEHOLDER.format(idx=idx))
            table.replace_with(placeholder)
        except Exception:
            logger.debug(f"Failed to convert table {idx} to markdown, skipping")
            table.decompose()

    return tables_md


def _clean_html_to_text(soup: BeautifulSoup) -> str:
    """Convert BeautifulSoup to clean plaintext, preserving paragraph structure."""
    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "meta", "link", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")

    # Collapse excessive whitespace while preserving paragraph breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    # Strip each line
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(lines)

    # Remove common boilerplate patterns
    text = re.sub(r"(?i)table of contents?\s*\n", "", text)

    return text.strip()


def _get_section_map(filing_type: str) -> dict[str, dict]:
    """Return the section definitions for the given filing type."""
    ft = filing_type.upper().replace("-", "")
    if ft == "10K":
        return SECTIONS_10K
    elif ft == "10Q":
        return SECTIONS_10Q
    elif ft == "8K":
        return SECTIONS_8K
    return {}


def _detect_sections(
    text: str,
    filing_type: str,
    section_map: dict[str, dict],
    tables_md: dict[int, str],
) -> list[ParsedSection]:
    """Detect section boundaries in the filing text and split into ParsedSections."""
    if not section_map:
        return []

    # Find all item header matches with their positions
    matches = list(_ITEM_PATTERN.finditer(text))
    if not matches:
        return []

    # Deduplicate: for each item number, keep only the LAST match
    # (the first occurrence is often the TOC, the later one is the actual section)
    seen_items: dict[str, re.Match] = {}
    for m in matches:
        item_num = m.group(1).upper()
        seen_items[item_num] = m

    # Sort by position in document
    unique_matches = sorted(seen_items.values(), key=lambda m: m.start())

    sections: list[ParsedSection] = []
    for i, match in enumerate(unique_matches):
        item_num = match.group(1).upper()

        # Look up section metadata
        section_info = section_map.get(item_num)
        if not section_info:
            continue

        # Determine section boundaries
        start = match.end()
        end = unique_matches[i + 1].start() if i + 1 < len(unique_matches) else len(text)

        section_text = text[start:end].strip()

        # Skip very short sections (likely just a header with no content)
        if len(section_text) < 50:
            continue

        # Extract tables that belong to this section
        section_tables = []
        for idx, table_md in tables_md.items():
            placeholder = f"[[TABLE_PLACEHOLDER_{idx}]]"
            if placeholder in section_text:
                section_tables.append(table_md)
                section_text = section_text.replace(placeholder, "")

        section_text = section_text.strip()

        sections.append(ParsedSection(
            section_id=f"item_{item_num.lower()}",
            section_name=section_info["name"],
            category=section_info["category"],
            text_content=section_text,
            tables=section_tables,
        ))

    return sections

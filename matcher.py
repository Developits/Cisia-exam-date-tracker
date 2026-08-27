#!/usr/bin/env python3
"""
Matching Engine and Date Utilities for CISIA Filters.
Provides university matching, date range validation, and filter row evaluation.

University matching strategy:
  - No alias dictionary (removed to prevent short-name false positives like 'bari' in 'Cagliari').
  - Uses word-boundary case-insensitive substring matching against the live CISIA row fields.
  - Falls back to difflib fuzzy ratio for close misspellings.
"""

import re
import difflib
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
import logging

import config

logger = logging.getLogger("CISIA-Matcher")


def normalize_text(text: str) -> str:
    """Lowercases and condenses whitespace. Keeps word characters only."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(cleaned.split())


def parse_date_str(date_str: str) -> date | None:
    """Parses date string in formats DD/MM/YYYY, YYYY-MM-DD, or DD-MM-YYYY."""
    if not date_str:
        return None
    cleaned = date_str.strip()
    formats = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_user_date_range(text: str, default_year: int = None) -> tuple[str | None, str | None]:
    """
    Parses flexible user inputs into (start_date_str, end_date_str) in 'YYYY-MM-DD' format.
    Accepts:
      - '10/08/2026 - 15/09/2026' or '10/08 to 15/09'
      - 'August 2026' or 'August to September'
      - '2026-08-10 to 2026-09-15'
    """
    if not text:
        return None, None

    year = default_year or datetime.now(ZoneInfo(config.TIMEZONE)).year
    cleaned = text.strip()

    # Case: Preset "Next 30 Days" / "Next 60 Days"
    if "30" in cleaned and "day" in cleaned.lower():
        now_d = datetime.now(ZoneInfo(config.TIMEZONE)).date()
        return now_d.isoformat(), (now_d + timedelta(days=30)).isoformat()
    if "60" in cleaned and "day" in cleaned.lower():
        now_d = datetime.now(ZoneInfo(config.TIMEZONE)).date()
        return now_d.isoformat(), (now_d + timedelta(days=60)).isoformat()

    # Month name mapping
    months = {
        "jan": 1, "january": 1, "gen": 1, "gennaio": 1,
        "feb": 2, "february": 2, "febbraio": 2,
        "mar": 3, "march": 3, "marzo": 3,
        "apr": 4, "april": 4, "aprile": 4,
        "may": 5, "maggio": 5,
        "jun": 6, "june": 6, "giugno": 6,
        "jul": 7, "july": 7, "luglio": 7,
        "aug": 8, "august": 8, "agosto": 8,
        "sep": 9, "sept": 9, "september": 9, "settembre": 9,
        "oct": 10, "october": 10, "ottobre": 10,
        "nov": 11, "november": 11, "novembre": 11,
        "dec": 12, "december": 12, "dicembre": 12
    }

    # Match numeric ranges like "10/08/2026 - 15/09/2026" or "10/08 - 15/09"
    range_match = re.search(
        r"(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](\d{2,4}))?\s*(?:-|to|until|–|—)\s*(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](\d{2,4}))?",
        cleaned, re.IGNORECASE
    )
    if range_match:
        d1, m1, y1, d2, m2, y2 = range_match.groups()
        year1 = int(y1) if y1 else year
        if year1 < 100:
            year1 += 2000
        year2 = int(y2) if y2 else (year1 if y1 else year)
        if year2 < 100:
            year2 += 2000
        try:
            start_dt = date(year1, int(m1), int(d1))
            end_dt = date(year2, int(m2), int(d2))
            if start_dt > end_dt:
                start_dt, end_dt = end_dt, start_dt
            return start_dt.isoformat(), end_dt.isoformat()
        except ValueError:
            pass

    # Match single date "15/09/2026"
    single_match = re.search(r"(\d{1,2})[/\-\.](\d{1,2})(?:[/\-\.](\d{2,4}))?", cleaned)
    if single_match:
        d, m, y = single_match.groups()
        year_val = int(y) if y else year
        if year_val < 100:
            year_val += 2000
        try:
            dt = date(year_val, int(m), int(d))
            return dt.isoformat(), dt.isoformat()
        except ValueError:
            pass

    # Match named months range e.g., "August to September" or "10 August to 15 September"
    norm = cleaned.lower()
    found_months = []
    for name, num in months.items():
        if re.search(rf"\b{re.escape(name)}\b", norm):
            found_months.append(num)

    if found_months:
        found_months = sorted(list(set(found_months)))
        m_start = found_months[0]
        m_end = found_months[-1]
        try:
            start_dt = date(year, m_start, 1)
            next_m = m_end + 1 if m_end < 12 else 1
            next_y = year if m_end < 12 else year + 1
            end_dt = date(next_y, next_m, 1) - timedelta(days=1)
            return start_dt.isoformat(), end_dt.isoformat()
        except ValueError:
            pass

    return None, None


def match_university(query: str, target_university: str, target_city: str = "", target_region: str = "") -> tuple[bool, float, str]:
    """
    Evaluates whether a target university row matches the user's typed query.

    Strategy (no alias dictionary — eliminates false positives like 'bari' in 'Cagliari'):
      1. ANY → always matches.
      2. Word-boundary substring: each word in query must appear as a whole word in
         the combined target string (university + city + region).
      3. Fuzzy ratio via difflib against the university name for close misspellings.

    Returns (is_match, confidence_score, matched_name).
    """
    if not query or query.strip().upper() == "ANY":
        return True, 1.0, "Any University"

    q_norm = normalize_text(query)
    target_norm = normalize_text(target_university)
    city_norm = normalize_text(target_city)
    region_norm = normalize_text(target_region)

    combined_target = f"{target_norm} {city_norm} {region_norm}"

    # 1. Word-boundary match: every query token must be a whole word in combined target
    stop_words = {"university", "of", "di", "degli", "studi", "the", "la", "le", "li"}
    q_tokens = [t for t in q_norm.split() if len(t) > 1 and t not in stop_words]

    if q_tokens:
        all_match = all(
            re.search(rf"\b{re.escape(tok)}\b", combined_target)
            for tok in q_tokens
        )
        if all_match:
            return True, 0.90, target_university

    # 2. Fuzzy ratio via difflib for misspellings (e.g. "Sapineza" → "Sapienza")
    #    Compare against the full name AND the first significant word (most distinctive part)
    ratio = difflib.SequenceMatcher(None, q_norm, target_norm).ratio()
    if ratio >= 0.70:
        return True, ratio, target_university

    # Fuzzy against just the first significant word of the university (e.g. "sapienza")
    first_word = target_norm.split()[0] if target_norm else ""
    if len(first_word) > 3 and first_word not in ("the", "universita", "university"):
        first_ratio = difflib.SequenceMatcher(None, q_norm, first_word).ratio()
        if first_ratio >= 0.80:
            return True, first_ratio, target_university

    # 3. Fuzzy against city name
    if city_norm:
        city_ratio = difflib.SequenceMatcher(None, q_norm, city_norm).ratio()
        if city_ratio >= 0.80:
            return True, city_ratio, target_university

    return False, 0.0, ""


def match_exam_type(filter_exam_type: str, row_test_type: str) -> bool:
    """
    Checks if the row test type matches the filter exam type.
    filter_exam_type may be a comma-separated list (multi-select), e.g.:
      'TOLC-I (Engineering),CEnT-S (English)'
    A row matches if it matches ANY of the selected exam types (OR logic).
    """
    if not filter_exam_type or filter_exam_type.strip().upper() in ("ALL", "ANY"):
        return True

    r_norm = normalize_text(row_test_type)

    # Split comma-separated exam types and check each one
    exam_types = [e.strip() for e in filter_exam_type.split(",") if e.strip()]

    for exam_type in exam_types:
        f_norm = normalize_text(exam_type)

        # TOLC-I / Engineering
        if "tolc i" in f_norm or "engineering" in f_norm or "ingegneria" in f_norm:
            if "tolc i" in r_norm or "engineering" in r_norm or "ingegneria" in r_norm:
                return True

        # TOLC-E / Economics
        elif "tolc e" in f_norm or "economics" in f_norm or "economia" in f_norm:
            if "tolc e" in r_norm or "economics" in r_norm or "economia" in r_norm:
                return True

        # CEnT-S: use strict pattern to avoid matching unrelated words containing "cent"
        elif "cent s" in f_norm or "cents" in f_norm or "cent-s" in f_norm:
            if re.search(r"\bcent[\s\-]?s\b", r_norm) or "cents" in r_norm:
                return True

        # Fallback: direct substring
        else:
            if f_norm in r_norm or r_norm in f_norm:
                return True

    return False


def is_date_in_range(test_date_str: str, start_date_str: str = None, end_date_str: str = None) -> bool:
    """Verifies that test_date is within [start_date, end_date] (inclusive)."""
    t_date = parse_date_str(test_date_str)
    if not t_date:
        return False

    if start_date_str:
        s_date = parse_date_str(start_date_str)
        if s_date and t_date < s_date:
            return False

    if end_date_str:
        e_date = parse_date_str(end_date_str)
        if e_date and t_date > e_date:
            return False

    return True


def row_matches_filter(row: dict, filter_dict: dict) -> bool:
    """
    Comprehensive evaluation of a scraped CISIA row against a user filter.
    Enforces strictly @HOME / @CASA modality, matching exam type (multi-select),
    university (word-boundary fuzzy), and date window.
    """
    # 1. Modality check: Strictly TOLC@HOME / CENT@HOME / TOLC@CASA
    fmt = (row.get("format") or "").upper()
    if "HOME" not in fmt and "CASA" not in fmt:
        return False

    # 2. Exam Type check (supports comma-separated multi-exam filter)
    if not match_exam_type(filter_dict.get("exam_type", "ALL"), row.get("test_type", "")):
        return False

    # 3. University check (word-boundary fuzzy, no alias dictionary)
    uni_query = filter_dict.get("university_query", "ANY")
    uni_match, _, _ = match_university(
        uni_query,
        row.get("university", ""),
        row.get("city", ""),
        row.get("region", "")
    )
    if not uni_match:
        return False

    # 4. Date window check
    start_d = filter_dict.get("start_date")
    end_d = filter_dict.get("end_date")
    if not is_date_in_range(row.get("date", ""), start_d, end_d):
        return False

    return True

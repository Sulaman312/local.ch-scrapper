"""
§5.3 Pipedrive duplicate check (before creating a record).

Match order:
  1. Website OR MoneyHouse company identity
  2. Phone number
  3. Fuzzy company name (with location bias when available)
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse


FUZZY_NAME_THRESHOLD = 0.88
MatchResult = Tuple[Optional[Dict[str, Any]], Optional[str]]


def normalize_website(value: Any) -> str:
    if value is None or value == '' or value == 'N/A':
        return ''
    text = str(value).strip().lower()
    if not text:
        return ''
    if '://' not in text:
        text = 'https://' + text
    try:
        parsed = urlparse(text)
    except Exception:
        return ''
    host = (parsed.netloc or '').removeprefix('www.')
    path = (parsed.path or '').rstrip('/')
    if not host:
        return ''
    return f'{host}{path}'


def normalize_moneyhouse_key(value: Any) -> str:
    """Normalize a MoneyHouse company URL/path to a stable identity key."""
    if value is None or value == '' or value == 'N/A':
        return ''
    text = str(value).strip().lower()
    if not text:
        return ''
    if '://' not in text and text.startswith('/'):
        text = 'https://www.moneyhouse.ch' + text
    elif '://' not in text and 'moneyhouse' not in text:
        # Bare company slug/id
        return re.sub(r'\s+', '', text)

    try:
        parsed = urlparse(text)
    except Exception:
        return ''

    host = (parsed.netloc or '').removeprefix('www.')
    if host and 'moneyhouse.ch' not in host:
        return ''

    path = (parsed.path or '').rstrip('/')
    match = re.search(r'/company/([^/]+)', path)
    if match:
        return match.group(1)
    return path.strip('/') or ''


def normalize_swiss_phone(raw: Any) -> Optional[str]:
    if raw is None or raw == '' or raw == 'N/A':
        return None

    cleaned = re.sub(r'[^\d+]', '', str(raw).strip())
    if cleaned.startswith('00'):
        cleaned = '+' + cleaned[2:]

    if re.fullmatch(r'\+41\d{9}', cleaned):
        return cleaned
    if re.fullmatch(r'0\d{9}', cleaned):
        return '+41' + cleaned[1:]
    if re.fullmatch(r'\d{9}', cleaned):
        return '+41' + cleaned
    if re.fullmatch(r'41\d{9}', cleaned):
        return '+' + cleaned
    return None


def extract_phones(record: Dict[str, Any]) -> List[str]:
    values: List[str] = []
    for key in ('phone_numbers', 'phone_numbers_raw', 'mobile_numbers', 'landline_numbers'):
        raw = record.get(key)
        if not raw or raw == 'N/A':
            continue
        if isinstance(raw, list):
            parts = raw
        else:
            parts = re.split(r'[,;/|]', str(raw))
        for part in parts:
            normalized = normalize_swiss_phone(part)
            if normalized and normalized not in values:
                values.append(normalized)
    return values


def normalize_name(value: Any) -> str:
    text = (str(value) if value is not None else '').lower()
    text = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)
    return re.sub(r'\s+', ' ', text).strip()


def names_fuzzy_match(left: Any, right: Any, threshold: float = FUZZY_NAME_THRESHOLD) -> bool:
    a = normalize_name(left)
    b = normalize_name(right)
    if not a or not b:
        return False
    if a == b:
        return True
    ratio = SequenceMatcher(None, a, b).ratio()
    if ratio >= threshold:
        return True
    # Token containment helps with "Foo AG" vs "Foo"
    a_tokens = {t for t in a.split() if len(t) > 2}
    b_tokens = {t for t in b.split() if len(t) > 2}
    if a_tokens and b_tokens:
        overlap = len(a_tokens & b_tokens) / max(len(a_tokens), len(b_tokens))
        if overlap >= 0.8 and ratio >= (threshold - 0.05):
            return True
    return False


def location_compatible(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    """Prefer fuzzy matches in the same place when location is known."""
    left_zip = str(left.get('zipcode') or '').strip()
    right_zip = str(right.get('zipcode') or '').strip()
    if left_zip and right_zip:
        return left_zip == right_zip

    left_city = normalize_name(left.get('city'))
    right_city = normalize_name(right.get('city'))
    if left_city and right_city:
        return left_city == right_city

    # If either side lacks location, allow the name match.
    return True


def record_identity(record: Dict[str, Any]) -> Dict[str, Any]:
    website = normalize_website(record.get('website'))
    moneyhouse = normalize_moneyhouse_key(
        record.get('moneyhouse_url') or record.get('moneyhouse_company_url')
    )
    phones = extract_phones(record)
    return {
        'website': website,
        'moneyhouse': moneyhouse,
        'phones': phones,
        'title': record.get('title') or record.get('name') or '',
    }


def find_pipedrive_duplicate(
    candidate: Dict[str, Any],
    existing_records: Sequence[Dict[str, Any]],
) -> MatchResult:
    """
    §5.3 three-tier match against already-known records.

    Returns (matched_record, tier) where tier is one of:
    website, moneyhouse, phone, fuzzy_name — or (None, None).
    """
    cand = record_identity(candidate)

    # Tier 1a: website
    if cand['website']:
        for record in existing_records:
            other = normalize_website(record.get('website'))
            if other and other == cand['website']:
                return record, 'website'

    # Tier 1b: MoneyHouse company identity
    if cand['moneyhouse']:
        for record in existing_records:
            other = normalize_moneyhouse_key(
                record.get('moneyhouse_url') or record.get('moneyhouse_company_url')
            )
            if other and other == cand['moneyhouse']:
                return record, 'moneyhouse'

    # Tier 2: phone
    if cand['phones']:
        cand_phones = set(cand['phones'])
        for record in existing_records:
            other_phones = set(extract_phones(record))
            if cand_phones & other_phones:
                return record, 'phone'

    # Tier 3: fuzzy name (+ location bias)
    if cand['title']:
        for record in existing_records:
            other_title = record.get('title') or record.get('name') or ''
            if names_fuzzy_match(cand['title'], other_title) and location_compatible(candidate, record):
                return record, 'fuzzy_name'

    return None, None


def _sort_key(record: Dict[str, Any]) -> Tuple[float, str]:
    score = record.get('credibility_score')
    try:
        score_val = float(score) if score is not None and score != '' else -1.0
    except (TypeError, ValueError):
        score_val = -1.0
    title = str(record.get('title') or '')
    return (score_val, title)


def dedupe_for_pipedrive_create(
    candidates: Iterable[Dict[str, Any]],
    existing_records: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Keep only records that should create a new Pipedrive org.

    - Matches against `existing_records` (e.g. companies from prior jobs) are skipped.
    - Within `candidates`, later duplicates of an already-kept row are skipped.
    Prefer higher credibility_score when collapsing within-batch duplicates.
    """
    existing = list(existing_records or [])
    ordered = sorted(list(candidates), key=_sort_key, reverse=True)

    kept: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    known_pool: List[Dict[str, Any]] = list(existing)

    for record in ordered:
        match, tier = find_pipedrive_duplicate(record, known_pool)
        if match is not None:
            skipped.append({
                'title': record.get('title'),
                'url': record.get('url'),
                'dedupe_tier': tier,
                'matched_title': match.get('title') or match.get('name'),
                'matched_url': match.get('url'),
                'matched_id': str(match.get('_id')) if match.get('_id') is not None else None,
            })
            continue

        kept.append(record)
        known_pool.append(record)

    return {
        'create_rows': kept,
        'skipped_duplicates': skipped,
        'rows_before': len(ordered),
        'rows_after': len(kept),
    }

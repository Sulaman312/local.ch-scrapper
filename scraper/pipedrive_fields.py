"""
Pipedrive §5.1 field mapping.

Maps internal scraper fields → export column names and optional Pipedrive
custom-field API keys (hashes). Keys are loaded from environment variables so
they can be confirmed/filled without code changes (§7 item 2).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


# Canonical §5.1-oriented mapping. `env_key` holds the Pipedrive custom field hash.
FIELD_DEFINITIONS: List[Dict[str, str]] = [
    {"internal": "title", "export_name": "Organization", "env_key": "PIPEDRIVE_FIELD_ORGANIZATION"},
    {"internal": "street", "export_name": "Address", "env_key": "PIPEDRIVE_FIELD_ADDRESS"},
    {"internal": "zipcode", "export_name": "ZIP", "env_key": "PIPEDRIVE_FIELD_ZIP"},
    {"internal": "city", "export_name": "City", "env_key": "PIPEDRIVE_FIELD_CITY"},
    {"internal": "canton", "export_name": "Canton", "env_key": "PIPEDRIVE_FIELD_CANTON"},
    {"internal": "landline_numbers", "export_name": "Phone", "env_key": "PIPEDRIVE_FIELD_PHONE"},
    {"internal": "mobile_numbers", "export_name": "Mobile", "env_key": "PIPEDRIVE_FIELD_MOBILE"},
    {"internal": "email", "export_name": "Email", "env_key": "PIPEDRIVE_FIELD_EMAIL"},
    {"internal": "website", "export_name": "Website", "env_key": "PIPEDRIVE_FIELD_WEBSITE"},
    {"internal": "moneyhouse_url", "export_name": "MoneyHouse URL", "env_key": "PIPEDRIVE_FIELD_MONEYHOUSE_URL"},
    {"internal": "gmb_url", "export_name": "GMB URL", "env_key": "PIPEDRIVE_FIELD_GMB_URL"},
    {"internal": "gmb_rating", "export_name": "GMB rating", "env_key": "PIPEDRIVE_FIELD_GMB_RATING"},
    {"internal": "gmb_review_count", "export_name": "GMB reviews", "env_key": "PIPEDRIVE_FIELD_GMB_REVIEWS"},
    {"internal": "has_local_search", "export_name": "Local Search", "env_key": "PIPEDRIVE_FIELD_LOCAL_SEARCH"},
    {"internal": "has_localch_banner_ads", "export_name": "Local.ch banner ads", "env_key": "PIPEDRIVE_FIELD_BANNER_ADS"},
    {"internal": "has_web_banner_ads", "export_name": "Web banner ads", "env_key": "PIPEDRIVE_FIELD_WEB_BANNER_ADS"},
    {"internal": "yellow_rated", "export_name": "Yellow rated", "env_key": "PIPEDRIVE_FIELD_YELLOW_RATED"},
    {"internal": "robot_flags", "export_name": "Robot flags", "env_key": "PIPEDRIVE_FIELD_ROBOT_FLAGS"},
    {"internal": "credibility_score", "export_name": "Credibility score", "env_key": "PIPEDRIVE_FIELD_CREDIBILITY_SCORE"},
    {"internal": "score_model_version", "export_name": "Score model", "env_key": "PIPEDRIVE_FIELD_SCORE_MODEL"},
    {"internal": "copyright_year", "export_name": "Copyright year", "env_key": "PIPEDRIVE_FIELD_COPYRIGHT_YEAR"},
    {"internal": "url", "export_name": "Local.ch URL", "env_key": "PIPEDRIVE_FIELD_LOCALCH_URL"},
    {"internal": "keyword", "export_name": "Keyword", "env_key": "PIPEDRIVE_FIELD_KEYWORD"},
]


def _load_json_overrides() -> Dict[str, str]:
    """Optional JSON file: {\"PIPEDRIVE_FIELD_MOBILE\": \"abc123...\", ...}."""
    path = os.getenv('PIPEDRIVE_FIELD_KEYS_FILE', '').strip()
    if not path:
        default = Path(__file__).resolve().parent.parent / 'config' / 'pipedrive_field_keys.json'
        path = str(default) if default.exists() else ''
    if not path or not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    except Exception:
        return {}
    return {}


def get_field_key_map() -> Dict[str, Dict[str, Optional[str]]]:
    """
    Returns {internal: {export_name, pipedrive_key, env_key, configured}}.
    """
    file_overrides = _load_json_overrides()
    mapping: Dict[str, Dict[str, Optional[str]]] = {}
    for item in FIELD_DEFINITIONS:
        env_key = item['env_key']
        api_key = (os.getenv(env_key) or file_overrides.get(env_key) or '').strip() or None
        mapping[item['internal']] = {
            'export_name': item['export_name'],
            'pipedrive_key': api_key,
            'env_key': env_key,
            'configured': bool(api_key),
        }
    return mapping


def field_keys_status() -> Dict[str, Any]:
    mapping = get_field_key_map()
    configured = [k for k, v in mapping.items() if v['configured']]
    missing = [k for k, v in mapping.items() if not v['configured']]
    return {
        'total_fields': len(mapping),
        'configured_count': len(configured),
        'missing_count': len(missing),
        'configured': configured,
        'missing': missing,
        'fields': mapping,
        'use_api_keys_as_headers': os.getenv('PIPEDRIVE_EXPORT_USE_API_KEYS', 'false').strip().lower() == 'true',
    }


def _serialize_cell(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def remap_dataframe_for_pipedrive(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a Pipedrive-oriented dataframe:
    - Prefer configured custom-field API keys as headers when enabled
    - Otherwise use human export names from §5.1 mapping
    - Keep unmapped columns with original names at the end
    """
    if df is None or df.empty:
        return df

    status = field_keys_status()
    mapping = status['fields']
    use_keys = status['use_api_keys_as_headers']

    ordered_cols: List[str] = []
    rename_map: Dict[str, str] = {}

    for internal, meta in mapping.items():
        if internal not in df.columns:
            # Fallbacks for phone when split fields absent (legacy rows)
            if internal == 'landline_numbers' and 'phone_numbers' in df.columns:
                internal_src = 'phone_numbers'
            else:
                continue
        else:
            internal_src = internal

        if use_keys and meta['pipedrive_key']:
            header = meta['pipedrive_key']
        else:
            header = meta['export_name']

        # Avoid colliding headers
        if header in rename_map.values():
            header = f"{header} ({internal})"

        rename_map[internal_src] = header
        if internal_src not in ordered_cols:
            ordered_cols.append(internal_src)

    remaining = [c for c in df.columns if c not in ordered_cols]
    out = df[ordered_cols + remaining].copy()
    for col in out.columns:
        out[col] = out[col].map(_serialize_cell)
    out = out.rename(columns=rename_map)
    return out


def build_field_keys_sheet() -> pd.DataFrame:
    """Audit sheet for operators confirming §5.1 / §7 item 2 keys."""
    rows = []
    for internal, meta in get_field_key_map().items():
        rows.append({
            'internal_field': internal,
            'export_name': meta['export_name'],
            'env_key': meta['env_key'],
            'pipedrive_api_key': meta['pipedrive_key'] or '',
            'configured': meta['configured'],
        })
    return pd.DataFrame(rows)

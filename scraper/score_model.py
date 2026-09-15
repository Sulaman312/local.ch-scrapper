"""
Reconciled credibility / lead-priority score model (v3).

Ads sign conflict — resolution
------------------------------
Local.ch banner/display ads are a *yellow/robot* sales-risk signal (already buying
Local Search commercial products), NOT a positive profile-quality boost.

They share the same commercial family as `has_local_search`. To avoid stacking two
correlated −10 hits for one underlying “paid Local.ch customer” state, Local Search
and Local.ch banner ads share one capped commercial penalty bucket.

Copyright recency remains an independent robot penalty.
Profile completeness is always non-negative and sums to 100 at full strength.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List


SCORE_MODEL_VERSION = "reconciled_v3"

# Profile completeness (max 100)
PTS_DESCRIPTION_FULL = 20
PTS_DESCRIPTION_PARTIAL = 10
PTS_PICTURES_FULL = 20
PTS_PICTURES_MID = 12
PTS_PICTURES_LOW = 6
PTS_REVIEWS_FULL = 20
PTS_REVIEWS_MID = 12
PTS_REVIEWS_LOW = 6
PTS_PHONE = 5
PTS_MOBILE = 5
PTS_EMAIL = 5
PTS_WEBSITE = 5
PTS_SOCIAL = 10
PTS_ADDRESS = 10

# Yellow/robot penalties (negative for outbound priority)
PTS_LOCALCH_COMMERCIAL = -10  # Local Search OR Local.ch banner ads (shared bucket)
PTS_COPYRIGHT_VERY_RECENT = -10
PTS_COPYRIGHT_RECENT = -5


def _truthy(value: Any) -> bool:
    return value is True or value == 'true' or value == 'Yes' or value == 'yes'


def calculate_credibility_score(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return score plus breakdown/flags.

    Keys:
      credibility_score, score_model_version, score_breakdown,
      robot_flags, yellow_rated, profile_score, robot_penalty
    """
    breakdown: Dict[str, int] = {}
    robot_flags: List[str] = []

    # --- Profile completeness ---
    description = data.get('description') or ''
    if description and len(description) > 100:
        breakdown['description'] = PTS_DESCRIPTION_FULL
    elif description:
        breakdown['description'] = PTS_DESCRIPTION_PARTIAL
    else:
        breakdown['description'] = 0

    pictures = int(data.get('picture_count') or 0)
    if pictures >= 5:
        breakdown['pictures'] = PTS_PICTURES_FULL
    elif pictures >= 3:
        breakdown['pictures'] = PTS_PICTURES_MID
    elif pictures >= 1:
        breakdown['pictures'] = PTS_PICTURES_LOW
    else:
        breakdown['pictures'] = 0

    reviews = int(data.get('review_count') or 0)
    if reviews >= 10:
        breakdown['reviews'] = PTS_REVIEWS_FULL
    elif reviews >= 5:
        breakdown['reviews'] = PTS_REVIEWS_MID
    elif reviews >= 1:
        breakdown['reviews'] = PTS_REVIEWS_LOW
    else:
        breakdown['reviews'] = 0

    has_any_phone = bool(
        data.get('phone_numbers')
        or data.get('landline_numbers')
        or data.get('mobile_numbers')
    )
    breakdown['phone'] = PTS_PHONE if has_any_phone else 0
    breakdown['mobile'] = (
        PTS_MOBILE if (data.get('has_mobile') or data.get('mobile_numbers')) else 0
    )
    breakdown['email'] = PTS_EMAIL if data.get('email') else 0
    breakdown['website'] = PTS_WEBSITE if data.get('website') else 0
    breakdown['social_media'] = PTS_SOCIAL if _truthy(data.get('has_social_media')) else 0
    breakdown['address'] = (
        PTS_ADDRESS
        if (data.get('street') and data.get('zipcode') and data.get('city'))
        else 0
    )

    profile_score = sum(breakdown.values())

    # --- Yellow/robot adjustments ---
    robot_penalty = 0
    has_local_search = _truthy(data.get('has_local_search'))
    has_banner_ads = _truthy(data.get('has_localch_banner_ads'))

    if has_local_search:
        robot_flags.append('local_search')
    if has_banner_ads:
        robot_flags.append('localch_banner_ads')

    # Shared commercial bucket resolves ads/local-search double-count conflict.
    if has_local_search or has_banner_ads:
        breakdown['localch_commercial'] = PTS_LOCALCH_COMMERCIAL
        robot_penalty += PTS_LOCALCH_COMMERCIAL
        robot_flags.append('localch_commercial')
    else:
        breakdown['localch_commercial'] = 0

    copyright_year = data.get('copyright_year')
    copyright_pts = 0
    if copyright_year and copyright_year not in ('N/A', '', None):
        try:
            year = int(copyright_year)
            current_year = datetime.now().year
            if year >= current_year - 1:
                copyright_pts = PTS_COPYRIGHT_VERY_RECENT
                robot_flags.append('copyright_very_recent')
            elif year >= current_year - 3:
                copyright_pts = PTS_COPYRIGHT_RECENT
                robot_flags.append('copyright_recent')
        except (TypeError, ValueError):
            copyright_pts = 0
    breakdown['copyright'] = copyright_pts
    robot_penalty += copyright_pts

    # Deduplicate flags while preserving order
    seen = set()
    unique_flags = []
    for flag in robot_flags:
        if flag not in seen:
            seen.add(flag)
            unique_flags.append(flag)

    raw = profile_score + robot_penalty
    credibility_score = max(0, min(100, raw))

    return {
        'credibility_score': credibility_score,
        'score_model_version': SCORE_MODEL_VERSION,
        'score_breakdown': breakdown,
        'profile_score': profile_score,
        'robot_penalty': robot_penalty,
        'robot_flags': unique_flags,
        'yellow_rated': bool(unique_flags),
    }

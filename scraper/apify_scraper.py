"""Apify-backed local.ch acquisition with the legacy dashboard data contract.

Only local.ch acquisition lives here. Optional website, Moneyhouse, directory,
and Google Places enrichment remains in :mod:`scraper` and is applied by the
existing application orchestration.
"""

from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from typing import Callable, Dict, List, Optional

import requests


APIFY_BASE_URL = "https://api.apify.com/v2"
DEFAULT_ACTOR_ID = "abotapi/local-ch-scraper"
DEFAULT_LOCATION = "switzerland"
DEFAULT_PAGE_SIZE = 20

logger = logging.getLogger(__name__)


class ApifyConfigError(RuntimeError):
    """Raised when required Apify configuration is missing or invalid."""


class ApifyRunError(RuntimeError):
    """Raised when an Apify Actor run or dataset request fails."""


class ApifyRunStopped(RuntimeError):
    """Raised after an in-flight Actor run is stopped by the user."""


_DAY_FIELDS = {
    "monday": "hours_monday",
    "montag": "hours_monday",
    "lundi": "hours_monday",
    "lunedi": "hours_monday",
    "lunedì": "hours_monday",
    "tuesday": "hours_tuesday",
    "dienstag": "hours_tuesday",
    "mardi": "hours_tuesday",
    "martedi": "hours_tuesday",
    "martedì": "hours_tuesday",
    "wednesday": "hours_wednesday",
    "mittwoch": "hours_wednesday",
    "mercredi": "hours_wednesday",
    "mercoledi": "hours_wednesday",
    "mercoledì": "hours_wednesday",
    "thursday": "hours_thursday",
    "donnerstag": "hours_thursday",
    "jeudi": "hours_thursday",
    "giovedi": "hours_thursday",
    "giovedì": "hours_thursday",
    "friday": "hours_friday",
    "freitag": "hours_friday",
    "vendredi": "hours_friday",
    "venerdi": "hours_friday",
    "venerdì": "hours_friday",
    "saturday": "hours_saturday",
    "samstag": "hours_saturday",
    "samedi": "hours_saturday",
    "sabato": "hours_saturday",
    "sunday": "hours_sunday",
    "sonntag": "hours_sunday",
    "dimanche": "hours_sunday",
    "domenica": "hours_sunday",
}

_DAY_ABBREVIATIONS = {
    "mon": "hours_monday",
    "tue": "hours_tuesday",
    "wed": "hours_wednesday",
    "thu": "hours_thursday",
    "fri": "hours_friday",
    "sat": "hours_saturday",
    "sun": "hours_sunday",
}


class ApifyLocalChScraper:
    """Run the local.ch Actor and normalize its dataset for this application."""

    def __init__(
        self,
        keyword: str,
        helper,
        progress_callback=None,
        should_stop: Optional[Callable[[], bool]] = None,
        session: Optional[requests.Session] = None,
    ):
        self.keyword = keyword
        self.helper = helper
        self.progress_callback = progress_callback
        self.should_stop = should_stop
        self.session = session or requests.Session()
        self.results: List[Dict] = []
        self.current_run_id: Optional[str] = None
        self.current_dataset_id: Optional[str] = None

        self.api_token = os.getenv("APIFY_API_TOKEN", "").strip()
        self.actor_id = os.getenv("APIFY_ACTOR_ID", DEFAULT_ACTOR_ID).strip() or DEFAULT_ACTOR_ID
        self.location = (
            os.getenv("APIFY_DEFAULT_LOCATION", DEFAULT_LOCATION).strip()
            or DEFAULT_LOCATION
        )
        self.run_timeout = self._positive_int("APIFY_RUN_TIMEOUT_SECONDS", 600)
        self.poll_interval = self._positive_int("APIFY_POLL_INTERVAL_SECONDS", 5)
        self.page_size = self._positive_int("APIFY_PAGE_SIZE", DEFAULT_PAGE_SIZE)
        self.language = os.getenv("APIFY_LANGUAGE", "fr").strip().lower() or "fr"
        if self.language not in {"de", "en", "fr", "it"}:
            raise ApifyConfigError("APIFY_LANGUAGE must be one of: de, en, fr, it")

        if not self.api_token:
            raise ApifyConfigError("APIFY_API_TOKEN is not configured")

        use_proxy = os.getenv("APIFY_USE_PROXY", "true").strip().lower() == "true"
        proxy_groups = [
            value.strip()
            for value in os.getenv("APIFY_PROXY_GROUPS", "RESIDENTIAL").split(",")
            if value.strip()
        ]
        self.proxy_config = {"useApifyProxy": use_proxy}
        if use_proxy and proxy_groups:
            self.proxy_config["apifyProxyGroups"] = proxy_groups
            self.proxy_config["apifyProxyCountry"] = "CH"

    @staticmethod
    def _positive_int(name: str, default: int) -> int:
        raw = os.getenv(name, str(default)).strip()
        try:
            value = int(raw)
        except ValueError as exc:
            raise ApifyConfigError(f"{name} must be an integer") from exc
        if value <= 0:
            raise ApifyConfigError(f"{name} must be greater than zero")
        return value

    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_token}"}

    def _report(self, stage: str, message: str, **extra) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(stage=stage, message=message, **extra)
            except Exception as exc:
                logger.warning("Apify progress callback failed: %s", exc)
        logger.info("[%s] %s", stage, message)

    def _stop_requested(self) -> bool:
        return bool(self.should_stop and self.should_stop())

    def _run_actor(self, run_input: Dict) -> str:
        if self._stop_requested():
            raise ApifyRunStopped("Stop requested before the Apify run started")

        actor_path = self.actor_id.replace("/", "~")
        response = self.session.post(
            f"{APIFY_BASE_URL}/acts/{actor_path}/runs",
            headers=self._headers,
            json=run_input,
            timeout=30,
        )
        if response.status_code not in (200, 201):
            raise ApifyRunError(
                f"Failed to start Apify Actor: HTTP {response.status_code} "
                f"{response.text[:300]}"
            )

        try:
            run_id = response.json()["data"]["id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ApifyRunError("Apify returned an invalid run response") from exc

        self.current_run_id = run_id
        self._report(
            "apify_run_started",
            "Local.ch acquisition started",
            run_id=run_id,
        )
        return run_id

    def _abort_run(self, run_id: str) -> None:
        try:
            self.session.post(
                f"{APIFY_BASE_URL}/actor-runs/{run_id}/abort",
                headers=self._headers,
                timeout=30,
            )
        except requests.RequestException as exc:
            logger.warning("Could not abort Apify run %s: %s", run_id, exc)

    def _wait_for_run(self, run_id: str) -> Dict:
        deadline = time.monotonic() + self.run_timeout
        while time.monotonic() < deadline:
            if self._stop_requested():
                self._abort_run(run_id)
                raise ApifyRunStopped("Scraping stopped by user request")

            try:
                response = self.session.get(
                    f"{APIFY_BASE_URL}/actor-runs/{run_id}",
                    headers=self._headers,
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()["data"]
                status = data["status"]
            except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
                raise ApifyRunError(f"Could not read Apify run {run_id}: {exc}") from exc

            if status == "SUCCEEDED":
                self.current_dataset_id = data.get("defaultDatasetId")
                self._report(
                    "apify_run_succeeded",
                    "Local.ch acquisition completed",
                    run_id=run_id,
                    dataset_id=self.current_dataset_id,
                )
                return data
            if status in {"FAILED", "ABORTED", "TIMED-OUT"}:
                raise ApifyRunError(f"Apify run ended with status {status}")

            self._report(
                "apify_run_polling",
                f"Local.ch acquisition is {status.lower()}",
                run_id=run_id,
            )
            time.sleep(self.poll_interval)

        self._abort_run(run_id)
        raise ApifyRunError(f"Apify run exceeded the {self.run_timeout}s timeout")

    def _fetch_dataset_items(self, dataset_id: str) -> List[Dict]:
        items: List[Dict] = []
        offset = 0
        limit = 1000
        while True:
            try:
                response = self.session.get(
                    f"{APIFY_BASE_URL}/datasets/{dataset_id}/items",
                    headers=self._headers,
                    params={
                        "format": "json",
                        "clean": "true",
                        "offset": offset,
                        "limit": limit,
                    },
                    timeout=60,
                )
                response.raise_for_status()
                batch = response.json()
            except (requests.RequestException, ValueError) as exc:
                raise ApifyRunError(f"Could not fetch Apify dataset: {exc}") from exc

            if not isinstance(batch, list):
                raise ApifyRunError("Apify dataset response was not a list")
            items.extend(item for item in batch if isinstance(item, dict))
            if len(batch) < limit:
                return items
            offset += len(batch)

    @staticmethod
    def _string(value) -> str:
        if value is None:
            return ""
        return value if isinstance(value, str) else str(value)

    @staticmethod
    def _local_ch_slug(value: str) -> str:
        """Match the ASCII slugs generated by the Actor's search mode."""
        normalized = unicodedata.normalize("NFKD", value or "")
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")

    @staticmethod
    def _format_hours_interval(interval) -> str:
        if not isinstance(interval, dict):
            return str(interval) if interval else ""
        start = interval.get("start")
        end = interval.get("end")
        if start and end:
            return f"{start}-{end}"
        if start:
            return f"from {start}"
        return ""

    def _parse_opening_hours(self, item: Dict) -> Dict[str, str]:
        hours = {field: "" for field in set(_DAY_FIELDS.values())}
        structured = item.get("openingHoursStructured")
        if isinstance(structured, list):
            for entry in structured:
                if not isinstance(entry, dict):
                    continue
                day = str(entry.get("day") or "").strip().lower()
                field = _DAY_FIELDS.get(day)
                if not field:
                    continue
                intervals = entry.get("intervals")
                if isinstance(intervals, list) and intervals:
                    parts = [self._format_hours_interval(value) for value in intervals]
                    hours[field] = " / ".join(value for value in parts if value)
                if not hours[field]:
                    status = str(entry.get("status") or "").lower()
                    if status == "closed":
                        hours[field] = "Closed"
                    elif status:
                        hours[field] = status.replace("_", " ").title()
            if any(hours.values()):
                return hours

        text = item.get("openingHours")
        if text:
            for segment in str(text).split(";"):
                day, separator, value = segment.partition(":")
                if not separator:
                    continue
                key = day.strip().lower()
                field = _DAY_FIELDS.get(key) or _DAY_ABBREVIATIONS.get(key)
                if field:
                    hours[field] = value.strip()
        return hours

    def _normalize_item(self, item: Dict) -> Dict:
        value = self._string
        title = value(item.get("name"))
        legal_name = value(item.get("subtitle")) or title
        street = value(item.get("street"))
        zipcode = value(item.get("zipCode"))
        city = value(item.get("city"))
        canton = value(item.get("canton")) or self.helper.derive_canton_from_zip(zipcode)
        phone_raw = ", ".join(
            value(number)
            for number in (item.get("phone"), item.get("phoneAlt"), item.get("mobile"))
            if number
        )
        phones = self.helper.normalize_phone_list(phone_raw)
        hours = self._parse_opening_hours(item)
        socials = {
            "facebook_url": value(item.get("facebook")),
            "instagram_url": value(item.get("instagram")),
            "linkedin_url": value(item.get("linkedin")),
            "twitter_url": value(item.get("twitter")),
            "youtube_url": value(item.get("youtube")),
        }
        image_urls = item.get("imageUrls") if isinstance(item.get("imageUrls"), list) else []
        premium = bool(item.get("isPremium"))
        rating = item.get("rating")
        attribute_groups = self._attribute_groups(item)

        return {
            "url": value(item.get("detailUrl")),
            "keyword": self.keyword,
            "title": title,
            "street": street,
            "zipcode": zipcode,
            "city": city,
            "canton": canton,
            "address_enriched": bool(street and zipcode and city and canton),
            "phone_numbers": phones["phone_numbers"],
            "phone_numbers_raw": phone_raw,
            "mobile_numbers": phones["mobile_numbers"],
            "landline_numbers": phones["landline_numbers"],
            "has_mobile": phones["has_mobile"],
            "email": value(item.get("email")),
            "website": value(item.get("website")),
            "description": value(item.get("description")),
            "picture_count": len(
                [url for url in image_urls if url and not str(url).startswith("data:")]
            ),
            "review_count": item.get("ratingCount") or item.get("reviewCount") or 0,
            "average_rating": "" if rating is None else str(rating),
            "has_social_media": any(socials.values()),
            **socials,
            "copyright_year": "N/A",
            "has_local_search": "N/A",
            "has_localch_banner_ads": premium,
            "localch_banner_ad_signals": ["isPremium"] if premium else [],
            "has_web_banner_ads": "N/A",
            **hours,
            "credibility_score": 0,
            "score_model_version": "",
            "score_breakdown": {},
            "profile_score": 0,
            "robot_penalty": 0,
            "robot_flags": [],
            "yellow_rated": False,
            "languages": attribute_groups["languages"],
            "forms_of_contact": attribute_groups["forms_of_contact"],
            "location_attributes": attribute_groups["location_attributes"],
            "categories": item.get("categories") if isinstance(item.get("categories"), list) else [],
            "is_independent": None,
            "independent_classification": "",
            "independent_classification_reason": "",
            "independent_classification_source": "",
            "zip": "N/A",
            "persons": [],
            "moneyhouse_url": "N/A",
            "on_architectes_ch": "N/A",
            "on_bienvivre_ch": "N/A",
            **self.helper.empty_gmb_profile(disabled=True),
            # Preserve the complete Actor result in MongoDB even when a field
            # has no equivalent in the existing dashboard contract. The API
            # and exports deliberately omit this internal archive for now.
            "apify_data": item,
            # Internal-only values are removed before Mongo insertion.
            "_apify_listing_id": value(item.get("id")),
            "_legal_name": legal_name,
        }

    @staticmethod
    def _attribute_groups(item: Dict) -> Dict[str, List[str]]:
        result = {
            "languages": [],
            "forms_of_contact": [],
            "location_attributes": [],
        }
        groups = item.get("attributeGroupsRaw")
        if not isinstance(groups, list):
            return result

        for group in groups:
            if not isinstance(group, dict):
                continue
            group_name = str(group.get("groupName") or "").strip().lower()
            attributes = group.get("attributes")
            if not isinstance(attributes, list):
                continue
            values = []
            for attribute in attributes:
                if isinstance(attribute, dict):
                    value = attribute.get("name") or attribute.get("value")
                else:
                    value = attribute
                if value and str(value).strip() not in values:
                    values.append(str(value).strip())

            if any(token in group_name for token in ("language", "sprache", "langue", "lingua")):
                result["languages"].extend(values)
            elif any(token in group_name for token in ("contact", "kontakt")):
                result["forms_of_contact"].extend(values)
            elif any(token in group_name for token in ("location", "standort", "emplacement", "posizione")):
                result["location_attributes"].extend(values)
        return result

    def _requested_range(
        self,
        max_pages: Optional[int],
        start_page: int,
        max_companies: Optional[int],
    ) -> tuple[int, Optional[int], int]:
        start_page = max(1, int(start_page or 1))
        # Continuations start from a page-specific local.ch URL, so the Actor's
        # dataset contains only the newly requested page window.
        offset = 0

        page_window = None
        if max_pages:
            end_page = max(start_page, int(max_pages))
            page_window = (end_page - start_page + 1) * self.page_size

        company_limit = None
        if max_companies and int(max_companies) > 0:
            company_limit = int(max_companies)

        limits = [value for value in (page_window, company_limit) if value is not None]
        selected_count = min(limits) if limits else None
        selection_end = offset + selected_count if selected_count is not None else None

        # No speculative 2x over-fetch: every emitted Actor result is billable.
        requested = 0 if selected_count is None else selected_count
        return offset, selection_end, max(0, requested)

    def search_by_keyword(
        self,
        max_pages: Optional[int] = None,
        start_page: int = 1,
        max_companies: Optional[int] = None,
    ) -> List[Dict]:
        """Acquire local.ch rows while preserving the dashboard's page inputs.

        The Actor is listing-based rather than page-based. ``start_page`` and
        the absolute ``max_pages`` endpoint are represented as a 20-row virtual
        page window so the existing UI and continuation flow remain unchanged.
        Full detail fetching is deliberately unconditional.
        """
        start_page = max(1, int(start_page or 1))
        offset, end, max_listings = self._requested_range(
            max_pages=max_pages,
            start_page=start_page,
            max_companies=max_companies,
        )
        if start_page > 1:
            category_slug = self._local_ch_slug(self.keyword)
            location_slug = self._local_ch_slug(self.location)
            run_input = {
                "mode": "url",
                "urls": [
                    f"https://www.local.ch/{self.language}/s/"
                    f"{category_slug}/{location_slug}?page={start_page}"
                ],
            }
        else:
            run_input = {
                "mode": "search",
                "category": self.keyword,
                "where": self.location,
            }
        run_input.update({
            "language": self.language,
            "maxListings": max_listings,
            "fetchDetails": True,
            "proxy": self.proxy_config,
        })
        if max_pages:
            # The UI stores an absolute endpoint; URL mode starts at start_page,
            # so tell the Actor only how many new pages to walk.
            run_input["maxPages"] = max(1, int(max_pages) - start_page + 1)
        self._report(
            "search_page_loading",
            "Collecting full local.ch profiles",
            page_number=start_page,
        )
        run_id = self._run_actor(run_input)
        run_data = self._wait_for_run(run_id)
        dataset_id = run_data.get("defaultDatasetId")
        if not dataset_id:
            raise ApifyRunError("Successful Apify run did not provide a dataset")

        raw_items = self._fetch_dataset_items(dataset_id)
        selected = raw_items[offset:end]
        normalized: List[Dict] = []
        seen = set()
        for item in selected:
            row = self._normalize_item(item)
            identity = row.get("_apify_listing_id") or row.get("url")
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            normalized.append(row)

        self.results = normalized
        self._report(
            "search_page_processed",
            f"Collected {len(normalized)} local.ch company profiles",
            page_number=start_page,
            found_links=len(normalized),
            new_links=len(normalized),
            total_links=len(normalized),
        )
        return normalized

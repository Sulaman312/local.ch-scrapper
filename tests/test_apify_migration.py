import logging
import os
import sys
import unittest
import ast
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

# The production image installs these declared dependencies. Keep this unit
# suite runnable in a minimal checkout where only requests is available; the
# tested enrichment methods do not exercise their import-time implementations.
for optional_module in (
    "selenium",
    "selenium.webdriver",
    "selenium.webdriver.common",
    "selenium.webdriver.common.by",
    "selenium.webdriver.support",
    "selenium.webdriver.support.ui",
    "selenium.webdriver.support.expected_conditions",
    "selenium.common",
    "selenium.common.exceptions",
    "pandas",
    "bs4",
    "pymongo",
):
    sys.modules.setdefault(optional_module, MagicMock())

from apify_scraper import ApifyLocalChScraper, ApifyRunStopped  # noqa: E402
from scraper import LocalChScraper  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, items):
        self.items = items
        self.posts = []
        self.gets = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if url.endswith("/abort"):
            return FakeResponse({"data": {"status": "ABORTING"}})
        return FakeResponse({"data": {"id": "run-1"}}, 201)

    def get(self, url, **kwargs):
        self.gets.append((url, kwargs))
        if "/actor-runs/" in url:
            return FakeResponse({
                "data": {
                    "status": "SUCCEEDED",
                    "defaultDatasetId": "dataset-1",
                }
            })
        if "/datasets/" in url:
            offset = int((kwargs.get("params") or {}).get("offset", 0))
            limit = int((kwargs.get("params") or {}).get("limit", 1000))
            return FakeResponse(self.items[offset:offset + limit])
        raise AssertionError(f"Unexpected URL: {url}")


class Helper:
    @staticmethod
    def derive_canton_from_zip(zipcode):
        return "ZH" if str(zipcode).startswith("8") else ""

    @staticmethod
    def normalize_phone_list(raw):
        values = [value.strip() for value in raw.split(",") if value.strip()]
        normalized = []
        mobiles = []
        landlines = []
        for value in values:
            digits = "".join(char for char in value if char.isdigit())
            phone = "+41" + digits[1:] if digits.startswith("0") else "+" + digits
            normalized.append(phone)
            (mobiles if phone.startswith("+4179") else landlines).append(phone)
        return {
            "phone_numbers": ", ".join(normalized),
            "mobile_numbers": ", ".join(mobiles),
            "landline_numbers": ", ".join(landlines),
            "has_mobile": bool(mobiles),
        }

    @staticmethod
    def empty_gmb_profile(disabled=False):
        value = "N/A" if disabled else ""
        return {
            "has_gmb": "N/A" if disabled else False,
            "gmb_place_id": value,
            "gmb_name": value,
            "gmb_url": value,
            "gmb_rating": value,
            "gmb_review_count": value if disabled else None,
            "gmb_formatted_address": value,
        }


def actor_item(index=0):
    return {
        "id": f"listing-{index}",
        "name": f"Company {index}",
        "subtitle": f"Company {index} AG",
        "street": f"Street {index}",
        "zipCode": "8001",
        "city": "Zurich",
        "canton": None,
        "phone": "044 123 45 67",
        "mobile": "079 123 45 67",
        "email": f"company{index}@example.test",
        "emailAlt": f"backup{index}@example.test",
        "fax": "044 123 45 68",
        "latitude": 47.3769,
        "longitude": 8.5417,
        "website": "https://example.test",
        "description": "A" * 120,
        "rating": 4.7,
        "ratingCount": 12,
        "imageUrls": ["photo-1", "data:image/svg+xml;base64,placeholder"],
        "facebook": "https://facebook.com/example",
        "categories": ["Plumber"],
        "attributeGroupsRaw": [
            {"groupName": "Languages", "attributes": [{"name": "French"}]},
            {"groupName": "Forms of contact", "attributes": [{"name": "By phone"}]},
            {"groupName": "Location", "attributes": [{"name": "Near station"}]},
        ],
        "isPremium": True,
        "detailUrl": f"https://www.local.ch/en/d/zurich/8001/x/listing-{index}",
        "openingHoursStructured": [
            {
                "day": "MONDAY",
                "status": "open",
                "intervals": [{"start": "08:00", "end": "17:00"}],
            },
            {"day": "SUNDAY", "status": "closed", "intervals": []},
        ],
    }


class ApifySourceTests(unittest.TestCase):
    def make_source(self, items, **kwargs):
        environment = {
            "APIFY_API_TOKEN": "test-token",
            "APIFY_ACTOR_ID": "abotapi/local-ch-scraper",
            "APIFY_DEFAULT_LOCATION": "switzerland",
            "APIFY_POLL_INTERVAL_SECONDS": "1",
        }
        with patch.dict(os.environ, environment, clear=False):
            return ApifyLocalChScraper(
                keyword="plumber",
                helper=Helper(),
                session=FakeSession(items),
                **kwargs,
            )

    def test_full_details_are_unconditional_and_page_window_is_hidden(self):
        source = self.make_source([actor_item(i) for i in range(25)])
        rows = source.search_by_keyword(max_pages=2, start_page=1)

        run_input = source.session.posts[0][1]["json"]
        self.assertIs(run_input["fetchDetails"], True)
        self.assertEqual(run_input["where"], "switzerland")
        self.assertEqual(run_input["language"], "fr")
        self.assertEqual(run_input["maxListings"], 40)
        self.assertEqual(run_input["maxPages"], 2)
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[0]["title"], "Company 0")

    def test_actor_payload_normalizes_to_existing_company_contract(self):
        source = self.make_source([actor_item()])
        row = source.search_by_keyword(max_pages=1)[0]

        self.assertEqual(row["canton"], "ZH")
        self.assertEqual(row["mobile_numbers"], "+41791234567")
        self.assertEqual(row["landline_numbers"], "+41441234567")
        self.assertEqual(row["review_count"], 12)
        self.assertEqual(row["picture_count"], 1)
        self.assertEqual(row["hours_monday"], "08:00-17:00")
        self.assertEqual(row["hours_sunday"], "Closed")
        self.assertTrue(row["has_social_media"])
        self.assertTrue(row["has_localch_banner_ads"])
        self.assertEqual(row["languages"], ["French"])
        self.assertEqual(row["forms_of_contact"], ["By phone"])
        self.assertEqual(row["location_attributes"], ["Near station"])
        self.assertEqual(row["apify_data"]["fax"], "044 123 45 68")
        self.assertEqual(row["apify_data"]["emailAlt"], "backup0@example.test")
        self.assertEqual(row["apify_data"]["latitude"], 47.3769)
        self.assertNotIn("raw", row)
        self.assertNotIn("fax", row)

    def test_blank_limits_preserve_scrape_all_behavior(self):
        source = self.make_source([actor_item()])
        source.search_by_keyword()
        run_input = source.session.posts[0][1]["json"]
        self.assertEqual(run_input["maxListings"], 0)
        self.assertNotIn("maxPages", run_input)

    def test_company_limit_is_not_doubled(self):
        source = self.make_source([actor_item(i) for i in range(5)])
        source.search_by_keyword(max_companies=1000)
        run_input = source.session.posts[0][1]["json"]
        self.assertEqual(run_input["maxListings"], 1000)

    def test_continuation_starts_from_page_url_without_refetch(self):
        source = self.make_source([actor_item(i) for i in range(20)])
        rows = source.search_by_keyword(
            max_pages=2,
            start_page=2,
        )

        run_input = source.session.posts[0][1]["json"]
        self.assertEqual(run_input["mode"], "url")
        self.assertEqual(
            run_input["urls"],
            ["https://www.local.ch/fr/s/plumber/switzerland?page=2"],
        )
        self.assertNotIn("resumeFromRunId", run_input)
        self.assertEqual(run_input["maxListings"], 20)
        self.assertEqual(run_input["maxPages"], 1)
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[0]["title"], "Company 0")

    def test_continuation_url_encodes_keyword(self):
        source = self.make_source([actor_item()])
        source.keyword = "vétérinaire à romandie"
        source.search_by_keyword(max_companies=1, start_page=2)
        run_input = source.session.posts[0][1]["json"]
        self.assertEqual(
            run_input["urls"],
            ["https://www.local.ch/fr/s/veterinaire-a-romandie/switzerland?page=2"],
        )

    def test_stop_before_start_does_not_spend_an_actor_run(self):
        source = self.make_source([actor_item()], should_stop=lambda: True)
        with self.assertRaises(ApifyRunStopped):
            source.search_by_keyword(max_pages=1)
        self.assertEqual(source.session.posts, [])

    def test_stop_during_run_aborts_actor(self):
        checks = {"count": 0}

        def should_stop():
            checks["count"] += 1
            return checks["count"] >= 2

        source = self.make_source([actor_item()], should_stop=should_stop)
        with self.assertRaises(ApifyRunStopped):
            source.search_by_keyword(max_pages=1)

        urls = [url for url, _ in source.session.posts]
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[-1].endswith("/actor-runs/run-1/abort"))


class ExistingEnrichmentTests(unittest.TestCase):
    def make_scraper(self):
        scraper = object.__new__(LocalChScraper)
        scraper.logger = logging.getLogger("test")
        scraper.include_independents = True
        scraper.check_websites = False
        scraper.check_zip = False
        scraper.check_moneyhouse = False
        scraper.check_architectes = False
        scraper.check_bienvivre = False
        scraper.check_gmb = False
        scraper.driver = None
        scraper.classify_title_with_openai = Mock(return_value={
            "is_independent": False,
            "classification": "has_legal_form",
            "reason": "test",
            "source": "test",
        })
        return scraper

    def test_google_places_remains_optional_without_selenium(self):
        scraper = self.make_scraper()
        scraper.check_gmb = True
        scraper.fetch_google_business_profile = Mock(return_value={
            "has_gmb": True,
            "gmb_place_id": "place-1",
            "gmb_name": "Company AG",
            "gmb_url": "https://maps.example.test/place-1",
            "gmb_rating": 4.8,
            "gmb_review_count": 20,
            "gmb_formatted_address": "Zurich",
        })
        row = actor_item()
        row = ApifyLocalChScraper._normalize_item(
            self.make_source_for_normalization(scraper), row
        )

        enriched = scraper.enrich_company_record(row)

        self.assertFalse(scraper.requires_browser_enrichment())
        self.assertTrue(enriched["has_gmb"])
        scraper.fetch_google_business_profile.assert_called_once()

    def test_existing_google_places_lookup_maps_api_response(self):
        scraper = self.make_scraper()
        scraper.google_places_enabled = True
        scraper.google_places_api_key = "google-test-key"
        scraper._places_session = Mock()
        scraper._places_session.post.return_value = FakeResponse({
            "places": [{
                "id": "place-1",
                "displayName": {"text": "Company 0 AG"},
                "formattedAddress": "Street 0, 8001 Zurich, Switzerland",
                "rating": 4.8,
                "userRatingCount": 20,
                "googleMapsUri": "https://maps.example.test/place-1",
            }]
        })

        result = scraper.fetch_google_business_profile(
            "Company 0 AG", street="Street 0", zipcode="8001", city="Zurich"
        )

        self.assertTrue(result["has_gmb"])
        self.assertEqual(result["gmb_rating"], 4.8)
        self.assertEqual(result["gmb_review_count"], 20)
        request = scraper._places_session.post.call_args
        self.assertEqual(request.kwargs["headers"]["X-Goog-Api-Key"], "google-test-key")

    @staticmethod
    def make_source_for_normalization(helper):
        source = object.__new__(ApifyLocalChScraper)
        source.keyword = "plumber"
        source.helper = helper
        return source

    def test_existing_selenium_options_are_applied_after_apify(self):
        scraper = self.make_scraper()
        scraper.check_websites = True
        scraper.check_zip = True
        scraper.check_moneyhouse = True
        scraper.check_architectes = True
        scraper.check_bienvivre = True
        scraper.driver = object()
        scraper.check_website_for_localsearch_and_copyright = Mock(
            return_value=("2022", True, True)
        )
        scraper.scrape_moneyhouse_persons = Mock(
            return_value=([{"name": "Director"}], "https://moneyhouse.example.test")
        )
        scraper.check_google_presence = Mock(side_effect=[True, False])
        source = self.make_source_for_normalization(scraper)
        row = source._normalize_item(actor_item())

        enriched = scraper.enrich_company_record(row)

        self.assertEqual(enriched["copyright_year"], "2022")
        self.assertTrue(enriched["has_local_search"])
        self.assertEqual(enriched["zip"], "Yes")
        self.assertEqual(enriched["persons"], [{"name": "Director"}])
        self.assertTrue(enriched["on_architectes_ch"])
        self.assertFalse(enriched["on_bienvivre_ch"])


class MigrationWiringTests(unittest.TestCase):
    def test_background_job_uses_apify_then_existing_enrichment_and_mongo(self):
        tree = ast.parse((ROOT / "frontend" / "app.py").read_text(encoding="utf-8"))
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "run_scraper_background"
        )
        calls = []
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                calls.append(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.append(node.func.attr)

        self.assertIn("ApifyLocalChScraper", calls)
        self.assertIn("search_by_keyword", calls)
        self.assertIn("enrich_company_record", calls)
        self.assertIn("insert_one", calls)
        self.assertNotIn("scrape_detail_page", calls)

    def test_continuation_does_not_pass_broken_apify_resume_id(self):
        app_source = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")
        dashboard = (ROOT / "frontend" / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("resume_run_id=resume_run_id", app_source)
        self.assertNotIn("resume_run_id: resumeRunId", dashboard)

    def test_existing_frontend_has_no_apify_specific_controls(self):
        template = (ROOT / "frontend" / "templates" / "index.html").read_text(encoding="utf-8")
        dashboard = (ROOT / "frontend" / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
        for forbidden in ("fetchDetails", "checkSocialSearch", 'id="backend"', 'id="location"'):
            self.assertNotIn(forbidden, template)
            self.assertNotIn(forbidden, dashboard)

    def test_raw_apify_archive_is_hidden_from_ui_and_exports(self):
        app_source = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")
        self.assertIn("find(query, {'apify_data': 0})", app_source)
        self.assertIn("{'apify_data': 0},", app_source)
        self.assertIn("row.pop('apify_data', None)", app_source)

    def test_progress_uses_friendly_steps_and_requested_page_range(self):
        app_source = (ROOT / "frontend" / "app.py").read_text(encoding="utf-8")
        dashboard = (ROOT / "frontend" / "static" / "js" / "dashboard.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("'Collecting company profiles'", app_source)
        self.assertIn("'All pages'", app_source)
        self.assertIn("<strong>Requested pages:</strong>", dashboard)
        self.assertNotIn("<strong>Stage:</strong>", dashboard)


if __name__ == "__main__":
    unittest.main()

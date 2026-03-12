from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import pandas as pd
import time
import logging
import re
import os
import requests
from datetime import datetime
from functools import wraps
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def retry_on_exception(retries=3, delay=5):
    """Retry decorator with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retry_count = 0
            while retry_count < retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retry_count += 1
                    if retry_count == retries:
                        raise e
                    wait_time = delay * (2 ** (retry_count - 1))
                    logging.warning(f"Attempt {retry_count} failed. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
            return None
        return wrapper
    return decorator

class LocalChScraper:
    def __init__(self, keyword="plumber", check_websites=False, check_moneyhouse=False, check_architectes=False, check_bienvivre=False):
        self.keyword = keyword
        self.check_websites = check_websites
        self.check_moneyhouse = check_moneyhouse
        self.check_architectes = check_architectes
        self.check_bienvivre = check_bienvivre
        self.driver = None
        self.results = []
        self.processed_urls = set()
        self.cookie_consent_handled = False  # Only handle once per session

        # Setup logging
        log_filename = f'scraping_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def setup_driver(self):
        """Initialize the Chrome WebDriver with anti-detection measures."""
        import os
        import shutil
        from selenium.webdriver.chrome.service import Service

        options = webdriver.ChromeOptions()

        options.add_argument('--headless=new')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        # For Railway/production - use system chromium and chromedriver
        service = None
        if os.path.exists('/nix/store'):
            # Find chromium in nix store
            chromium_path = shutil.which('chromium')
            chromedriver_path = shutil.which('chromedriver')

            if chromium_path:
                options.binary_location = chromium_path
                self.logger.info(f"Using system chromium: {chromium_path}")

            if chromedriver_path:
                service = Service(executable_path=chromedriver_path)
                self.logger.info(f"Using system chromedriver: {chromedriver_path}")

        try:
            if service:
                self.driver = webdriver.Chrome(service=service, options=options)
            else:
                self.driver = webdriver.Chrome(options=options)

            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.driver.implicitly_wait(10)
            self.driver.set_page_load_timeout(30)
            self.logger.info("WebDriver initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize WebDriver: {str(e)}")
            raise


    def export_to_excel(self, filename='scraped_results.xlsx'):
        """Export results to Excel file."""
        try:
            if not self.results:
                self.logger.warning("No data to export")
                return

            df = pd.DataFrame(self.results)
            df.to_excel(filename, index=False, engine='openpyxl')
            self.logger.info(f"Data exported to {filename} with {len(df)} records")

        except Exception as e:
            self.logger.error(f"Error exporting to Excel: {str(e)}")

    @staticmethod
    def _url_key(url):
        """Return the business-ID key for deduplication.

        The last path segment is the unique business ID and never changes
        across languages or category slugs.
        e.g. https://www.local.ch/de/d/rossrueti/9512/tierarzt/achilles-vetclinic-ag-5f77dQV5imYD91gct1Sesw
             https://www.local.ch/en/d/rossrueti/9512/vet/achilles-vetclinic-ag-5f77dQV5imYD91gct1Sesw
        Both → '5f77dQV5imYD91gct1Sesw'  (the trailing hash ID)
        """
        parsed = urlparse(url)
        last_segment = parsed.path.rstrip('/').split('/')[-1]
        # Extract the hash suffix after the last '-' (e.g. 'achilles-vetclinic-ag-5f77dQV5imYD91gct1Sesw' → '5f77dQV5imYD91gct1Sesw')
        if '-' in last_segment:
            return last_segment.split('-')[-1]
        return last_segment

    @retry_on_exception(retries=3, delay=5)
    def search_by_keyword(self, max_pages=None):
        """Search Local.ch by keyword and collect all company listings."""
        search_url = f"https://www.local.ch/fr/s/{self.keyword}"
        self.logger.info(f"Starting search for keyword: {self.keyword}")

        company_links = []
        page_number = 1

        while True:
            try:
                # Add page parameter if needed
                if page_number > 1:
                    if '?' in search_url:
                        url = f"{search_url}&page={page_number}"
                    else:
                        url = f"{search_url}?page={page_number}"
                else:
                    url = search_url

                self.logger.info(f"Scraping search results page {page_number}: {url}")

                self.driver.get(url)
                time.sleep(3)  # Wait for page to load

                # Find all company listing cards
                cards = self.driver.find_elements(By.CSS_SELECTOR, "article[data-testid^='list-element']")

                if not cards:
                    self.logger.info(f"No more results found on page {page_number}")
                    break

                self.logger.info(f"Found {len(cards)} listings on page {page_number}")

                for card in cards:
                    try:
                        # Extract company link
                        link_elem = card.find_element(By.CSS_SELECTOR, "a[href*='/d/']")
                        link = link_elem.get_attribute('href')

                        if link and link not in company_links:
                            company_links.append(link)

                    except NoSuchElementException:
                        continue

                # Check if there's a next page
                try:
                    # Look for next page button or check if we've reached max pages
                    if max_pages and page_number >= max_pages:
                        self.logger.info(f"Reached maximum number of pages ({max_pages})")
                        break

                    page_number += 1
                    time.sleep(2)  # Be nice to the server

                except Exception:
                    break

            except Exception as e:
                self.logger.error(f"Error on search page {page_number}: {str(e)}")
                break

        self.logger.info(f"Collected {len(company_links)} unique company links")
        return company_links

    def count_images(self):
        """Count number of images/pictures on the company profile."""
        try:
            # Look for gallery or image elements
            image_selectors = [
                "img[class*='gallery']",
                "img[class*='image']",
                "[data-cy*='image']",
                "[data-cy*='gallery']",
                ".DetailGallery_image",
                "img[src*='local.ch']"
            ]

            total_images = 0
            for selector in image_selectors:
                try:
                    images = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    # Filter out logo and small icons
                    valid_images = [img for img in images if img.size['width'] > 100 and img.size['height'] > 100]
                    total_images = max(total_images, len(valid_images))
                except:
                    continue

            return total_images
        except Exception as e:
            self.logger.warning(f"Error counting images: {str(e)}")
            return 0

    def count_reviews(self):
        """Count number of reviews on the company profile."""
        try:
            # Look for "Note moyenne (X avis)" pattern
            page_text = self.driver.find_element(By.TAG_NAME, 'body').text

            # Pattern: "Note moyenne (4 avis)" or "Durchschnitt (4 Bewertungen)"
            patterns = [
                r'Note moyenne \((\d+)\s*avis\)',          # French
                r'(\d+)\s*avis',                            # French simple
                r'Durchschnitt \((\d+)\s*Bewertungen\)',   # German
                r'(\d+)\s*Bewertungen',                     # German simple
                r'Average \((\d+)\s*reviews\)',             # English
                r'(\d+)\s*reviews',                         # English simple
            ]

            for pattern in patterns:
                match = re.search(pattern, page_text, re.IGNORECASE)
                if match:
                    review_count = int(match.group(1))
                    self.logger.info(f"  ✓ Reviews: {review_count}")
                    return review_count

            return 0
        except Exception as e:
            self.logger.warning(f"  Error counting reviews: {str(e)}")
            return 0

    def check_social_media_links(self):
        """Extract social media links and return them as a dictionary."""
        social_media_links = {
            'facebook_url': '',
            'instagram_url': '',
            'linkedin_url': '',
            'twitter_url': '',
            'youtube_url': ''
        }

        try:
            all_links = self.driver.find_elements(By.TAG_NAME, 'a')

            for link in all_links:
                href = link.get_attribute('href')
                if href:
                    href_lower = href.lower()

                    # Extract each social media platform URL
                    if 'facebook.com' in href_lower and not social_media_links['facebook_url']:
                        social_media_links['facebook_url'] = href
                        self.logger.info(f"  ✓ Facebook: {href}")
                    elif 'instagram.com' in href_lower and not social_media_links['instagram_url']:
                        social_media_links['instagram_url'] = href
                        self.logger.info(f"  ✓ Instagram: {href}")
                    elif 'linkedin.com' in href_lower and not social_media_links['linkedin_url']:
                        social_media_links['linkedin_url'] = href
                        self.logger.info(f"  ✓ LinkedIn: {href}")
                    elif 'twitter.com' in href_lower or 'x.com' in href_lower:
                        if not social_media_links['twitter_url']:
                            social_media_links['twitter_url'] = href
                            self.logger.info(f"  ✓ Twitter/X: {href}")
                    elif 'youtube.com' in href_lower and not social_media_links['youtube_url']:
                        social_media_links['youtube_url'] = href
                        self.logger.info(f"  ✓ YouTube: {href}")

            return social_media_links
        except Exception as e:
            self.logger.warning(f"Error checking social media: {str(e)}")
            return social_media_links

    def check_website_for_localsearch_and_copyright(self, website_url):
        """
        Visit company website using Selenium, find legal page, and extract:
        1. Copyright year (e.g., "© 2023")
        2. Local Search mention (e.g., "Realizzato da localsearch.ch")
        Returns: (copyright_year, has_local_search)
        """
        if not website_url or website_url == '':
            return '', False

        # Add https:// if missing
        if not website_url.startswith('http://') and not website_url.startswith('https://'):
            website_url = 'https://' + website_url
            self.logger.info(f"    Added https:// prefix: {website_url}")

        copyright_year = ''
        has_local_search = False

        try:
            self.logger.info(f"    Visiting website with browser: {website_url}")

            # Use Selenium to visit the website (avoids 403 errors)
            self.driver.get(website_url)
            time.sleep(2)  # Wait for page to load

            # Get page source
            page_source = self.driver.page_source
            soup = BeautifulSoup(page_source, 'html.parser')

            self.logger.info(f"    Page loaded successfully")

            # Look for legal/note-legali links in footer
            legal_link_patterns = [
                'note-legali', 'note legali', 'legal', 'mentions', 'impressum',
                'mentions-legales', 'mentions légales', 'rechtliches'
            ]

            legal_url = None

            # Find legal page link
            for link in soup.find_all('a', href=True):
                href = link.get('href', '').lower()
                link_text = link.get_text().lower()

                if any(pattern in href or pattern in link_text for pattern in legal_link_patterns):
                    legal_url = urljoin(website_url, link['href'])
                    self.logger.info(f"    Found legal page link: {legal_url}")
                    break

            # Visit the legal page if found
            if legal_url:
                try:
                    self.logger.info(f"    Navigating to legal page: {legal_url}")
                    self.driver.get(legal_url)
                    time.sleep(2)  # Wait for page to load

                    # Get page source
                    legal_page_source = self.driver.page_source
                    legal_soup = BeautifulSoup(legal_page_source, 'html.parser')

                    self.logger.info(f"    Legal page loaded successfully")

                    # Parse with BeautifulSoup to get clean text
                    legal_text = legal_soup.get_text()
                    legal_text_lower = legal_text.lower()
                    legal_html_lower = legal_page_source.lower()

                    # Check for Local Search mentions
                    self.logger.info(f"    Checking for Local Search indicators in legal page...")

                    # Look for specific patterns in HTML
                    if 'localsearch.ch' in legal_html_lower:
                        self.logger.info(f"      Found 'localsearch.ch' in HTML")

                       # Check for creation phrases
                        if any(phrase in legal_text_lower for phrase in [
                                'realizzato da',   # Italian: "Created by"
                                'realisiert durch', # German: "Created by"
                                'réalisé par',     # French: "Created by"
                                'erstellt von',    # German: "Created by"
                            ]):
                                has_local_search = True
                                self.logger.info(f"    ✓ Local Search found with creation phrase")

                            # Also check for "Eintrag auf local.ch" pattern
                        elif 'eintrag auf' in legal_text_lower and 'local.ch' in legal_text_lower:
                                has_local_search = True
                                self.logger.info(f"    ✓ Local Search found: 'Eintrag auf local.ch'")

                            # Check for "iscrizione su local.ch" (Italian)
                        elif 'iscrizione su' in legal_text_lower and 'local.ch' in legal_text_lower:
                                has_local_search = True
                                self.logger.info(f"    ✓ Local Search found: 'iscrizione su local.ch'")

                        else:
                                # Just finding localsearch.ch link is a strong indicator
                                has_local_search = True
                                self.logger.info(f"    ✓ Local Search found: localsearch.ch present")

                        if not has_local_search:
                            self.logger.info(f"    ✗ No Local Search indicators found")

                    # Extract copyright year from legal page
                    self.logger.info(f"    Searching for copyright year...")

                    # Search in the parsed text (BeautifulSoup removes HTML tags)
                    # Look for: "© 2019" or "© 2023" patterns
                    year_patterns = [
                        r'©\s*(\d{4})',           # © 2019
                        r'copyright\s*(\d{4})',   # Copyright 2019
                        r'\(c\)\s*(\d{4})',       # (c) 2019
                    ]

                    for pattern in year_patterns:
                        year_match = re.search(pattern, legal_text, re.IGNORECASE)
                        if year_match:
                            copyright_year = year_match.group(1)
                            self.logger.info(f"    ✓ Copyright year: {copyright_year}")
                            break

                    if not copyright_year:
                        self.logger.info(f"    ✗ No copyright year found on legal page")

                except Exception as e:
                    self.logger.warning(f"    Error visiting legal page: {str(e)}")

            # If no legal page found, check main page footer
            if not copyright_year or not has_local_search:
                footer = soup.find('footer')
                if footer:
                    footer_text = footer.get_text()

                    # Check for copyright year in footer
                    if not copyright_year:
                        copyright_match = re.search(r'©\s*(\d{4})', footer_text)
                        if copyright_match:
                            copyright_year = copyright_match.group(1)
                            self.logger.info(f"    ✓ Copyright year from footer: {copyright_year}")

                    # Check for Local Search in footer
                    if not has_local_search:
                        if 'localsearch' in footer_text.lower() or 'local.ch' in footer_text.lower():
                            has_local_search = True
                            self.logger.info(f"    ✓ Local Search found in footer!")

            return copyright_year, has_local_search

        except requests.exceptions.Timeout:
            self.logger.warning(f"    Timeout accessing website {website_url}")
            return '', False
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"    Request error for {website_url}: {str(e)}")
            return '', False
        except Exception as e:
            self.logger.warning(f"    Unexpected error checking website {website_url}: {str(e)}")
            return '', False

    def scrape_moneyhouse_persons(self, company_title):
        """Scrape person/management data from Moneyhouse.ch

        Returns: List of person dictionaries with name, role, since date, linkedin link
        """
        persons = []
        try:
            self.logger.info(f"  Checking Moneyhouse.ch for: {company_title}")

            # Navigate directly to search results page with company name
            import urllib.parse
            encoded_query = urllib.parse.quote(company_title)
            search_url = f"https://www.moneyhouse.ch/fr/search?q={encoded_query}&status=1&tab=companies"

            self.logger.info(f"    Navigating to: {search_url}")
            self.driver.get(search_url)

            # Wait for search results to load (language-agnostic selector)
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/company/']"))
                )
                self.logger.info(f"    Search results loaded")
            except:
                self.logger.info(f"    No search results found on Moneyhouse for: {company_title}")
                return persons

            # Find first company link (language-agnostic)
            # Look for any link containing '/company/' in the href
            company_link = None
            links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/company/']")

            self.logger.info(f"    Found {len(links)} company links on search page")

            # Try to find exact match first
            for link in links:
                link_text = link.text.strip()
                if link_text and link_text.lower() == company_title.lower():
                    company_link = link.get_attribute('href')
                    self.logger.info(f"    Found exact match: {link_text} -> {company_link}")
                    break

            # If no exact match, take the first result
            if not company_link and links:
                company_link = links[0].get_attribute('href')
                self.logger.info(f"    Using first result: {links[0].text.strip()} -> {company_link}")

            if not company_link:
                self.logger.info(f"    No company links found on Moneyhouse for: {company_title}")
                return persons

            # Navigate to management page
            # Ensure we have the full URL
            if not company_link.startswith('http'):
                company_link = 'https://www.moneyhouse.ch' + company_link

            management_url = company_link.rstrip('/') + '/management'
            self.logger.info(f"    Navigating to management page: {management_url}")
            self.driver.get(management_url)

            # Wait for person table to load
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "tbody.person"))
                )
            except:
                self.logger.info(f"    No management data found on Moneyhouse")
                return persons

            # Scrape person table data
            # The desktop table has ALL columns including roles and dates
            # The mobile table only has name and follow columns

            # First, let's see what tables exist
            all_tables = self.driver.find_elements(By.CSS_SELECTOR, "table")
            self.logger.info(f"    Total tables on page: {len(all_tables)}")

            for i, table in enumerate(all_tables[:5], 1):  # Check first 5 tables
                classes = table.get_attribute('class')
                tbody_count = len(table.find_elements(By.CSS_SELECTOR, "tbody.person"))
                self.logger.info(f"    Table {i}: classes='{classes}', tbody.person count={tbody_count}")

            # Try the desktop table selector
            person_rows = self.driver.find_elements(By.CSS_SELECTOR, "table.is-hidden-mobile tbody.person")
            self.logger.info(f"    Found {len(person_rows)} person rows with selector 'table.is-hidden-mobile tbody.person'")

            # If that didn't work, try without the table prefix
            if len(person_rows) == 0:
                self.logger.info(f"    Trying alternate selector...")
                # The desktop table has class containing "is-hidden-mobile" AND has td.entity-relationdate-sticky
                all_person_tbody = self.driver.find_elements(By.CSS_SELECTOR, "tbody.person")
                self.logger.info(f"    Found {len(all_person_tbody)} total tbody.person elements")

                # Filter to only those that have date columns (desktop table)
                person_rows = []
                for tbody in all_person_tbody:
                    has_date_column = len(tbody.find_elements(By.CSS_SELECTOR, "td.entity-relationdate-sticky")) > 0
                    self.logger.debug(f"    tbody has date column: {has_date_column}")
                    if has_date_column:
                        person_rows.append(tbody)

                self.logger.info(f"    Filtered to {len(person_rows)} person rows with date columns (desktop table)")

            for idx, row in enumerate(person_rows, 1):
                try:
                    person_data = {}

                    # Get the name link from the row
                    name_links = row.find_elements(By.CSS_SELECTOR, "a.name-link")
                    if not name_links:
                        self.logger.debug(f"    Row {idx}: No name link found, skipping")
                        continue

                    # Extract name from a.name-link
                    name_elem = name_links[0]
                    person_data['name'] = name_elem.text.strip()
                    person_data['profile_url'] = name_elem.get_attribute('href')

                    if not person_data['name']:
                        # Try getting text content via innerHTML or textContent
                        try:
                            text_content = self.driver.execute_script("return arguments[0].textContent;", name_elem)
                            person_data['name'] = text_content.strip() if text_content else ''
                            self.logger.debug(f"    Row {idx}: Got name via textContent: '{person_data['name']}'")
                        except:
                            pass

                    if not person_data['name']:
                        self.logger.debug(f"    Row {idx}: Empty name after all attempts, skipping")
                        # Log the HTML for debugging
                        try:
                            elem_html = name_elem.get_attribute('outerHTML')
                            self.logger.debug(f"    Row {idx} name element HTML: {elem_html[:200]}")
                        except:
                            pass
                        continue

                    # Extract roles from td.entity-relation-sticky span.role.bean
                    # Look within the row's tr element, not the tbody
                    tr_elem = row.find_element(By.TAG_NAME, "tr")

                    # Since we already verified the name_elem is displayed, this entire tr is visible
                    # No need to check is_displayed() again for each element within this row

                    # Get all role spans (there can be multiple like "Président" and "Signature individuelle")
                    role_spans = tr_elem.find_elements(By.CSS_SELECTOR, "td.entity-relation-sticky span.role.bean")
                    roles = []
                    for span in role_spans:
                        text = span.text.strip()
                        if not text:
                            # Try textContent
                            try:
                                text = self.driver.execute_script("return arguments[0].textContent;", span).strip()
                            except:
                                pass
                        if text:
                            roles.append(text)
                    person_data['role'] = ', '.join(roles) if roles else ''
                    self.logger.debug(f"    Row {idx}: Extracted roles: {person_data['role']}")

                    # Extract since date from td.entity-relationdate-sticky span
                    try:
                        date_span = tr_elem.find_element(By.CSS_SELECTOR, "td.entity-relationdate-sticky span")
                        date_text = date_span.text.strip()
                        if not date_text:
                            # Try textContent
                            date_text = self.driver.execute_script("return arguments[0].textContent;", date_span).strip()
                        # Remove language-specific prefixes
                        date_text = date_text.replace('depuis ', '').replace('seit ', '').replace('dal ', '')
                        person_data['since'] = date_text
                        self.logger.debug(f"    Row {idx}: Found date: {date_text}")
                    except Exception as e:
                        person_data['since'] = ''
                        self.logger.debug(f"    Row {idx}: Could not find date: {e}")

                    # Extract LinkedIn link if exists from a.icon-linkedIn
                    try:
                        linkedin_link = tr_elem.find_element(By.CSS_SELECTOR, "a.icon-linkedIn.linkedin-link")
                        person_data['linkedin'] = linkedin_link.get_attribute('href')
                        self.logger.debug(f"    Row {idx}: Found LinkedIn: {person_data['linkedin']}")
                    except Exception as e:
                        person_data['linkedin'] = ''
                        self.logger.debug(f"    Row {idx}: No LinkedIn link found: {e}")

                    persons.append(person_data)
                    self.logger.info(f"    Found person: {person_data['name']} - {person_data['role']} (since {person_data['since']})")

                except Exception as e:
                    self.logger.warning(f"    Error extracting person data from row {idx}: {e}")
                    # Log the HTML for debugging
                    try:
                        row_html = row.get_attribute('outerHTML')
                        self.logger.debug(f"    Row {idx} HTML: {row_html[:500]}...")  # First 500 chars
                    except:
                        pass
                    continue

            self.logger.info(f"    Total persons found: {len(persons)}")

            # If no persons found, save HTML to file for debugging
            if len(persons) == 0:
                try:
                    page_source = self.driver.page_source
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"moneyhouse_debug_{timestamp}.html"
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(page_source)
                    self.logger.warning(f"    No persons found! HTML saved to {filename} for debugging")
                except Exception as e:
                    self.logger.warning(f"    Could not save HTML debug file: {e}")

        except Exception as e:
            self.logger.error(f"  Error scraping Moneyhouse: {e}")
            # Save HTML to file for debugging
            try:
                if self.driver:
                    page_source = self.driver.page_source
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"moneyhouse_error_{timestamp}.html"
                    with open(filename, 'w', encoding='utf-8') as f:
                        f.write(page_source)
                    self.logger.error(f"  Error occurred! HTML saved to {filename} for debugging")
            except:
                pass

        return persons

    def check_google_presence(self, company_title, site_domain):
        """Check if company has presence on a specific site via DuckDuckGo search

        Args:
            company_title: Company name to search
            site_domain: Domain to check (e.g., 'architectes.ch')

        Returns: Boolean indicating presence
        """
        try:
            self.logger.info(f"  Checking {site_domain} presence for: {company_title}")

            # Use DuckDuckGo search with site: operator
            search_query = f'{company_title} site:{site_domain}'
            import urllib.parse
            encoded_query = urllib.parse.quote(search_query)
            ddg_url = f"https://duckduckgo.com/?q={encoded_query}"

            self.logger.info(f"    Searching DuckDuckGo: {ddg_url}")
            self.driver.get(ddg_url)
            time.sleep(1)  # Wait for page to load (reduced from 3)

            # DuckDuckGo uses different selectors - try multiple approaches
            # Try to find any search results
            result_selectors = [
                "article[data-testid='result']",  # Modern DDG
                "div.result",  # Classic DDG
                "div[data-testid='result']",  # Alternative
                "li[data-testid='result']",  # List item variant
                "a.result__a",  # Link variant
            ]

            results_found = False
            matching_results = []

            for selector in result_selectors:
                try:
                    results = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if results:
                        self.logger.info(f"    Found {len(results)} results using selector: {selector}")
                        results_found = True

                        # Check first 5 results for the domain
                        for idx, result in enumerate(results[:5], 1):
                            try:
                                # Get all links within this result
                                links = result.find_elements(By.TAG_NAME, "a")
                                for link in links:
                                    href = link.get_attribute('href')
                                    if href and site_domain.lower() in href.lower():
                                        # Make sure it's not a DDG internal link
                                        if 'duckduckgo.com' not in href.lower():
                                            self.logger.info(f"    ✓ Found on {site_domain}: {href}")
                                            return True
                            except:
                                continue

                        break  # Found results with this selector, no need to try others
                except:
                    continue

            # If no results found with standard selectors, try getting all links on page
            if not results_found:
                self.logger.info(f"    No standard results found, checking all links...")
                all_links = self.driver.find_elements(By.TAG_NAME, "a")

                for link in all_links:
                    try:
                        href = link.get_attribute('href')
                        if href and site_domain.lower() in href.lower():
                            # Exclude DDG's own links
                            if not any(x in href.lower() for x in ['duckduckgo.com', 'duck.co', 'privacy']):
                                self.logger.info(f"    ✓ Found on {site_domain}: {href}")
                                return True
                    except:
                        continue

            self.logger.info(f"    ✗ No results found on {site_domain}")
            return False

        except Exception as e:
            self.logger.error(f"  Error checking {site_domain} presence: {e}")
            # Save HTML for debugging
            try:
                page_source = self.driver.page_source
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"ddg_debug_{site_domain}_{timestamp}.html"
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(page_source)
                self.logger.info(f"    Debug HTML saved to {filename}")
            except:
                pass
            return False

    def calculate_credibility_score(self, data):
        """
        Calculate credibility score based on profile completeness.
        Total: 100 points
        """
        score = 0

        # Description (15 points)
        if data['description'] and len(data['description']) > 100:
            score += 15
        elif data['description']:
            score += 8

        # Pictures (15 points)
        if data['picture_count'] >= 5:
            score += 15
        elif data['picture_count'] >= 3:
            score += 10
        elif data['picture_count'] >= 1:
            score += 5

        # Reviews (15 points)
        if data['review_count'] >= 10:
            score += 15
        elif data['review_count'] >= 5:
            score += 10
        elif data['review_count'] >= 1:
            score += 5

        # Contact info (15 points)
        if data['phone_numbers']:
            score += 5
        if data['email']:
            score += 5
        if data['website']:
            score += 5

        # Social media (10 points)
        if data['has_social_media']:
            score += 10

        # Address (10 points)
        if data['street'] and data['zipcode'] and data['city']:
            score += 10

        # Local Search Detection (10 points) - NEGATIVE INDICATOR
        # Companies using Local Search are likely in contracts, less valuable leads
        if data['has_local_search']:
            score -= 10  # Penalty for being a Local Search customer

        # Copyright Year (10 points) - NEGATIVE INDICATOR for recent years
        # Recent copyright year (2024-2026) = likely in new contract
        if data['copyright_year']:
            try:
                year = int(data['copyright_year'])
                current_year = datetime.now().year

                if year >= current_year - 1:  # 2025 or 2026 (very recent)
                    score -= 10  # Strong penalty - definitely in contract
                elif year >= current_year - 3:  # 2023-2024 (recent)
                    score -= 5   # Moderate penalty - likely in contract
                # Older years (before 2023) get no penalty - contract likely expired
            except:
                pass

        # Ensure score stays within 0-100 range
        score = max(0, min(100, score))

        return score

    def clean_text(self, text):
        """Clean and format text."""
        if not text:
            return ''
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'<[^>]+>', '', text)
        return text.strip()

    def parse_address(self, address_text):
        """Parse address into components."""
        if not address_text:
            return '', '', '', ''

        address_text = address_text.replace('&nbsp;', ' ')
        address_text = re.sub(r'\s+', ' ', address_text.strip())

        pattern = r'(.*?)\s*,?\s*(\d{4})\s*(.*?)(?:\s*\((.*?)\))?$'
        match = re.match(pattern, address_text)

        if match:
            street = match.group(1).strip()
            zipcode = match.group(2)
            city = match.group(3).strip()
            kanton = match.group(4) or ''
            return street, zipcode, city, kanton.strip()

        return address_text, '', '', ''

    def handle_cookie_consent(self):
        """Handle cookie consent popup — only acts once per scraper session."""
        if self.cookie_consent_handled:
            return False

        try:
            # Short wait for popup to appear
            time.sleep(1)

            # Try to click "Tout refuser" (Refuse All) to avoid tracking
            try:
                refuse_button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Tout refuser')]"))
                )
                refuse_button.click()
                self.logger.info("Clicked 'Tout refuser' on cookie consent")
                time.sleep(1)
                self.cookie_consent_handled = True
                return True
            except:
                pass

            # If that fails, try to click "J'accepte" (Accept)
            try:
                accept_button = WebDriverWait(self.driver, 2).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'accepte')]"))
                )
                accept_button.click()
                self.logger.info("Clicked 'J'accepte' on cookie consent")
                time.sleep(1)
                self.cookie_consent_handled = True
                return True
            except:
                pass

            # No popup found — mark as handled so we don't check again
            self.cookie_consent_handled = True
            return False

        except Exception as e:
            self.logger.debug(f"No cookie consent popup found or error handling it: {str(e)}")
            self.cookie_consent_handled = True
            return False

    @retry_on_exception(retries=3, delay=5)
    def scrape_detail_page(self, url):
        """Scrape comprehensive data from a company detail page."""
        try:
            self.driver.get(url)

            # Handle cookie consent popup first
            self.handle_cookie_consent()

            # Wait for page to load
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.CLASS_NAME, "detail_detail__SXBfi")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-cy='header-title']")),
                        EC.presence_of_element_located((By.CLASS_NAME, "DetailMapPreview_addressValue__pQROv"))
                    )
                )
            except TimeoutException:
                self.logger.warning(f"Page load timeout for {url}")
                time.sleep(3)

        except Exception as e:
            self.logger.error(f"Error loading page {url}: {str(e)}")
            raise

        # Initialize data structure
        detail_data = {
            'url': url,
            'keyword': self.keyword,
            'title': '',
            'street': '',
            'zipcode': '',
            'city': '',
            'phone_numbers': '',
            'email': '',
            'website': '',
            'description': '',
            'picture_count': 0,
            'review_count': 0,
            'average_rating': '',
            'has_social_media': False,
            'facebook_url': '',
            'instagram_url': '',
            'linkedin_url': '',
            'twitter_url': '',
            'youtube_url': '',
            'copyright_year': '',
            'has_local_search': False,
            # Opening hours (7 days)
            'hours_monday': '',
            'hours_tuesday': '',
            'hours_wednesday': '',
            'hours_thursday': '',
            'hours_friday': '',
            'hours_saturday': '',
            'hours_sunday': '',
            'credibility_score': 0,
            # New fields from detail sections
            'languages': [],
            'forms_of_contact': [],
            'location_attributes': [],
            'categories': []
        }

        # Get title
        try:
            title = self.driver.find_element(By.CSS_SELECTOR, "[data-cy='header-title']")
            detail_data['title'] = title.text.strip()
            self.logger.info(f"  ✓ Title: {detail_data['title']}")
        except NoSuchElementException:
            self.logger.warning(f"  ✗ Title not found")

        # Disable implicit wait during data extraction — find_elements returns
        # immediately with an empty list instead of hanging for 10s per miss.
        self.driver.implicitly_wait(0)

        # Get all bordered info boxes (new Local.ch layout)
        info_boxes = self.driver.find_elements(By.CSS_SELECTOR, ".l\\:col.l\\:border")
        self.logger.info(f"  Found {len(info_boxes)} info boxes")

        # Process each info box
        for box in info_boxes:
            box_text = box.text.strip()
            self.logger.info(f"  Processing box with text starting: {box_text[:50]}...")

            # Check if this box contains address
            if 'Adresse:' in box_text or 'Address:' in box_text:
                try:
                    # Extract address after "Adresse:" label
                    lines = box_text.split('\n')
                    for i, line in enumerate(lines):
                        if 'Adresse:' in line or 'Address:' in line:
                            if i + 1 < len(lines):
                                address_text = lines[i + 1].strip()
                                street, zipcode, city, _ = self.parse_address(address_text)
                                detail_data.update({
                                    'street': street,
                                    'zipcode': zipcode,
                                    'city': city
                                })
                                self.logger.info(f"  ✓ Address: {street}, {zipcode} {city}")
                                break
                except Exception as e:
                    self.logger.warning(f"  Error parsing address: {str(e)}")

            # Check if this box contains contact info (phone, email, website)
            if any(keyword in box_text for keyword in ['Téléphone:', 'E-mail:', 'Site web:', 'Portable:', 'WhatsApp:']):
                try:
                    lines = box_text.split('\n')
                    for i, line in enumerate(lines):
                        line_lower = line.lower()

                        # Get phone number
                        if any(keyword in line for keyword in ['Téléphone:', 'Portable:', 'Phone:', 'Mobile:']):
                            # Collect all phone numbers after this label (skip labels like "Hauptnummer")
                            collected_phones = []
                            for j in range(i + 1, len(lines)):
                                next_line = lines[j].strip()

                                # Stop if we hit another label
                                if any(label in next_line for label in ['E-mail:', 'Site web:', 'Adresse:', 'Réseaux sociaux:']):
                                    break

                                # Skip sub-labels like "Hauptnummer", "Markus Bucher", etc (text without numbers)
                                # Only keep lines that contain actual phone numbers
                                if re.search(r'\d{2,}', next_line):  # At least 2 digits
                                    collected_phones.append(next_line)

                            if collected_phones:
                                phone_str = ', '.join(collected_phones)
                                if not detail_data['phone_numbers']:
                                    detail_data['phone_numbers'] = phone_str
                                else:
                                    detail_data['phone_numbers'] += f", {phone_str}"
                                self.logger.info(f"  ✓ Phone: {phone_str}")

                        # Get email
                        elif 'e-mail:' in line_lower or 'email:' in line_lower:
                            if i + 1 < len(lines):
                                detail_data['email'] = lines[i + 1].strip()
                                self.logger.info(f"  ✓ Email: {detail_data['email']}")

                        # Get website
                        elif 'site web:' in line_lower or 'website:' in line_lower:
                            if i + 1 < len(lines):
                                detail_data['website'] = lines[i + 1].strip()
                                self.logger.info(f"  ✓ Website: {detail_data['website']}")

                except Exception as e:
                    self.logger.warning(f"  Error parsing contact info: {str(e)}")

            # Check if this box contains description (class "gV")
            if 'gV' in box.get_attribute('class'):
                try:
                    detail_data['description'] = self.clean_text(box_text)
                    self.logger.info(f"  ✓ Description: {len(detail_data['description'])} chars")
                except Exception as e:
                    self.logger.warning(f"  Error parsing description: {str(e)}")

            # Check if this box contains opening hours
            if "Heures d'ouverture" in box_text or "Horaires" in box_text or "notOnMobile eD" in box.get_attribute('class'):
                try:
                    # Try to find opening hours elements
                    opening_hours_items = box.find_elements(By.CSS_SELECTOR, 'li[data-cy="opening-hours-weekdays"]')

                    if opening_hours_items:
                        self.logger.info(f"  Found {len(opening_hours_items)} opening hours entries")

                        # Map day names (French/German/Italian) to our field names
                        day_mapping = {
                            'lundi': 'hours_monday',
                            'monday': 'hours_monday',
                            'montag': 'hours_monday',
                            'lunedì': 'hours_monday',
                            'mardi': 'hours_tuesday',
                            'tuesday': 'hours_tuesday',
                            'dienstag': 'hours_tuesday',
                            'martedì': 'hours_tuesday',
                            'mercredi': 'hours_wednesday',
                            'wednesday': 'hours_wednesday',
                            'mittwoch': 'hours_wednesday',
                            'mercoledì': 'hours_wednesday',
                            'jeudi': 'hours_thursday',
                            'thursday': 'hours_thursday',
                            'donnerstag': 'hours_thursday',
                            'giovedì': 'hours_thursday',
                            'vendredi': 'hours_friday',
                            'friday': 'hours_friday',
                            'freitag': 'hours_friday',
                            'venerdì': 'hours_friday',
                            'samedi': 'hours_saturday',
                            'saturday': 'hours_saturday',
                            'samstag': 'hours_saturday',
                            'sabato': 'hours_saturday',
                            'dimanche': 'hours_sunday',
                            'sunday': 'hours_sunday',
                            'sonntag': 'hours_sunday',
                            'domenica': 'hours_sunday'
                        }

                        for item in opening_hours_items:
                            item_text = item.text.strip()
                            # Split into day and hours
                            parts = item_text.split('\n', 1)
                            if len(parts) == 2:
                                day_name = parts[0].strip().lower()
                                hours = parts[1].strip()

                                # Find matching field name
                                for key, field_name in day_mapping.items():
                                    if key in day_name:
                                        detail_data[field_name] = hours
                                        break

                        self.logger.info(f"  ✓ Opening hours extracted")

                except Exception as e:
                    self.logger.warning(f"  Error parsing opening hours: {str(e)}")

            # Check if this box contains average rating
            try:
                rating_elem = box.find_elements(By.CSS_SELECTOR, 'span[data-testid="average-rating"]')
                if rating_elem:
                    detail_data['average_rating'] = self.clean_text(rating_elem[0].text)
                    self.logger.info(f"  ✓ Average rating: {detail_data['average_rating']}")
            except Exception as e:
                self.logger.warning(f"  Error parsing average rating: {str(e)}")

        # Get languages
        try:
            headers = self.driver.find_elements(By.CLASS_NAME, "DescriptionContent_detailListTitle__hIIB6")

            for header in headers:
                if header.text.strip() == "Langues":
                    languages_dd = header.find_element(By.XPATH, "./following-sibling::dd[1]")
                    language_spans = languages_dd.find_elements(By.CLASS_NAME, "DescriptionContent_detailListContentAttribute__zhs_H")
                    langs = [span.text.strip().rstrip(',') for span in language_spans]
                    detail_data['languages'] = self.clean_text(', '.join(langs))
                    break
        except NoSuchElementException:
            pass

        # Count images/pictures
        detail_data['picture_count'] = self.count_images()

        # Count reviews
        detail_data['review_count'] = self.count_reviews()

        # Check for social media links and extract URLs
        social_media_links = self.check_social_media_links()
        detail_data['facebook_url'] = social_media_links['facebook_url']
        detail_data['instagram_url'] = social_media_links['instagram_url']
        detail_data['linkedin_url'] = social_media_links['linkedin_url']
        detail_data['twitter_url'] = social_media_links['twitter_url']
        detail_data['youtube_url'] = social_media_links['youtube_url']
        # Set has_social_media to True if any social media link found
        detail_data['has_social_media'] = any(social_media_links.values())

        # Restore implicit wait before any further navigation
        self.driver.implicitly_wait(10)

        # If website exists and check_websites is enabled, check for Local Search and copyright year
        if self.check_websites and detail_data['website']:
            self.logger.info(f"  Analyzing website: {detail_data['website']}")
            copyright_year, has_local_search = self.check_website_for_localsearch_and_copyright(detail_data['website'])
            detail_data['copyright_year'] = copyright_year
            detail_data['has_local_search'] = has_local_search
        else:
            # Set default values when website checking is disabled
            detail_data['copyright_year'] = 'N/A'
            detail_data['has_local_search'] = 'N/A'

        # Check Moneyhouse.ch for person/management data
        if self.check_moneyhouse:
            persons = self.scrape_moneyhouse_persons(detail_data['title'])
            detail_data['persons'] = persons
        else:
            detail_data['persons'] = []

        # Check Architectes.ch presence
        if self.check_architectes:
            detail_data['on_architectes_ch'] = self.check_google_presence(detail_data['title'], 'architectes.ch')
        else:
            detail_data['on_architectes_ch'] = 'N/A'

        # Check Editions-bienvivre.ch presence
        if self.check_bienvivre:
            detail_data['on_bienvivre_ch'] = self.check_google_presence(detail_data['title'], 'editions-bienvivre.ch')
        else:
            detail_data['on_bienvivre_ch'] = 'N/A'

        # Scrape Languages, Forms of contact, Location, Categories from detail sections
        try:
            # Find all h3 with class "ps" (section headers)
            section_headers = self.driver.find_elements(By.CSS_SELECTOR, "h3.ps")

            for header in section_headers:
                try:
                    header_text = header.text.strip().lower()

                    # Get ONLY the dd element that immediately follows this h3
                    next_element = header.find_element(By.XPATH, "./following-sibling::dd[1]")
                    value_spans = next_element.find_elements(By.CSS_SELECTOR, "span.pp")

                    values = [span.text.strip() for span in value_spans if span.text.strip()]

                    if 'language' in header_text or 'sprache' in header_text or 'langue' in header_text:
                        detail_data['languages'] = values
                        self.logger.info(f"  ✓ Languages: {', '.join(values)}")

                    elif 'forms of contact' in header_text or 'kontaktformen' in header_text or 'formes de contact' in header_text or 'forme' in header_text:
                        detail_data['forms_of_contact'] = values
                        self.logger.info(f"  ✓ Forms of contact: {', '.join(values)}")

                    elif 'location' in header_text or 'standort' in header_text or 'emplacement' in header_text:
                        detail_data['location_attributes'] = values
                        self.logger.info(f"  ✓ Location: {', '.join(values)}")

                except Exception as e:
                    self.logger.debug(f"  Error parsing section: {e}")

            # Scrape Categories (dt.ps followed by dd with links)
            try:
                category_headers = self.driver.find_elements(By.CSS_SELECTOR, "dt.ps")
                for header in category_headers:
                    if 'categor' in header.text.strip().lower():
                        parent = header.find_element(By.XPATH, "./..")
                        category_links = parent.find_elements(By.CSS_SELECTOR, "dd a.cH.pr")
                        categories = [link.text.strip() for link in category_links if link.text.strip()]
                        detail_data['categories'] = categories
                        self.logger.info(f"  ✓ Categories: {', '.join(categories)}")
                        break
            except Exception as e:
                self.logger.debug(f"  Error parsing categories: {e}")

        except Exception as e:
            self.logger.warning(f"  Error scraping detail sections: {e}")

        # Calculate credibility score
        detail_data['credibility_score'] = self.calculate_credibility_score(detail_data)

        return detail_data

    def scrape(self, max_search_pages=10, max_companies=None):
        """Main scraping function.

        Args:
            max_search_pages: Maximum number of search result pages to scrape
            max_companies: Maximum number of companies to scrape (None = all found)
        """
        try:
            # Setup WebDriver
            self.setup_driver()

            # Step 1: Search by keyword (with language filters applied via UI)
            company_links = self.search_by_keyword(max_pages=max_search_pages)

            if not company_links:
                self.logger.warning("No company links found")
                return

            self.logger.info(f"Found {len(company_links)} companies")

            # Step 2: Scrape each company's detail page
            # Limit companies if max_companies is specified
            if max_companies and max_companies > 0:
                max_companies = min(max_companies, len(company_links))
                self.logger.info(f"Limiting to {max_companies} companies")
            else:
                max_companies = len(company_links)
                self.logger.info(f"Scraping all {max_companies} companies")

            for i, link in enumerate(company_links[:max_companies], 1):
                if link in self.processed_urls:
                    self.logger.info(f"Skipping already processed link {i}/{max_companies}: {link}")
                    continue

                self.logger.info(f"Scraping company {i}/{max_companies}: {link}")

                try:
                    detail_data = self.scrape_detail_page(link)

                    if detail_data:
                        self.results.append(detail_data)
                        self.processed_urls.add(link)

                except Exception as e:
                    self.logger.error(f"Error processing link {link}: {str(e)}")
                    continue

                # Random delay to avoid being blocked
                import random
                delay = random.uniform(1, 2)
                time.sleep(delay)

            # Export to Excel (when run standalone)
            self.export_to_excel(f'{self.keyword}_scraped_results.xlsx')
            self.logger.info(f"Scraping completed! Total records: {len(self.results)}")

        except Exception as e:
            self.logger.error(f"Error during scraping: {str(e)}")
            # Try to export partial results
            try:
                self.export_to_excel(f'{self.keyword}_partial_results.xlsx')
            except:
                pass
        finally:
            if self.driver:
                self.driver.quit()

def main():
    # Example usage: scrape for "plumber"
    keyword = input("Enter search keyword (e.g., 'plumber', 'restaurant', 'dentist'): ").strip()
    if not keyword:
        keyword = "plumber"

    max_pages = input("Enter maximum number of search pages to scrape (default: 10): ").strip()
    if not max_pages:
        max_pages = 10
    else:
        max_pages = int(max_pages)

    scraper = LocalChScraper(keyword=keyword)
    scraper.scrape(max_search_pages=max_pages)

if __name__ == "__main__":
    main()

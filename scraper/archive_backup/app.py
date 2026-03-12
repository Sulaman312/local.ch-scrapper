from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import pandas as pd
import csv
import time
import logging
import re
import os
from datetime import datetime
from functools import wraps

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
                    wait_time = delay * (2 ** (retry_count - 1))  # Exponential backoff
                    logging.warning(f"Attempt {retry_count} failed. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
            return None
        return wrapper
    return decorator

class VetDetailScraper:
    def __init__(self):
        self.driver = None
        self.results = []
        self.checkpoint_file = 'scraping_checkpoint.csv'
        self.processed_urls = set()
        
        # Setup logging
        log_filename = f'scraping_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def setup_driver(self):
        """Initialize the Chrome WebDriver with appropriate options."""
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        
        try:
            self.driver = webdriver.Chrome(options=options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            self.driver.implicitly_wait(10)
            self.driver.set_page_load_timeout(30)
        except Exception as e:
            self.logger.error(f"Failed to initialize WebDriver: {str(e)}")
            raise

    def load_checkpoint(self):
        """Load previously processed URLs from checkpoint file."""
        if os.path.exists(self.checkpoint_file):
            try:
                df = pd.read_csv(self.checkpoint_file, encoding='utf-8-sig')
                self.processed_urls = set(df['url'].tolist())
                self.results = df.to_dict('records')
                self.logger.info(f"Loaded {len(self.processed_urls)} processed URLs from checkpoint")
            except Exception as e:
                self.logger.error(f"Error loading checkpoint: {str(e)}")
                self.processed_urls = set()
                self.results = []

    def save_checkpoint(self):
        """Save current progress to checkpoint file."""
        try:
            if self.results:
                df = pd.DataFrame(self.results)
                df.to_csv(self.checkpoint_file, index=False, encoding='utf-8-sig')
                self.logger.info(f"Saved checkpoint with {len(self.results)} records")
        except Exception as e:
            self.logger.error(f"Error saving checkpoint: {str(e)}")

    def export_to_excel(self, filename='scraped_data.xlsx'):
        """Export results to Excel file matching the expected format."""
        try:
            if not self.results:
                self.logger.warning("No data to export")
                return
                
            df = pd.DataFrame(self.results)
            
            # Ensure all required columns are present
            required_columns = [
                'url', 'Title', 'Address', 'logo_url', 'title', 'street', 
                'zipcode', 'city', 'kanton', 'phone_numbers', 'email', 
                'website', 'description', 'languages', 'Lundi', 'Mardi', 
                'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'
            ]
            
            for col in required_columns:
                if col not in df.columns:
                    df[col] = ''
            
            # Reorder columns to match expected format
            df = df[required_columns]
            
            # Export to Excel
            df.to_excel(filename, index=False, engine='openpyxl')
            self.logger.info(f"Data exported to {filename} with {len(df)} records")
            
        except Exception as e:
            self.logger.error(f"Error exporting to Excel: {str(e)}")

    def clean_time_text(self, text):
        """Clean and format time text."""
        if not text or text.lower() == 'fermé':
            return 'Fermé'
            
        text = re.sub(r'\s+', ' ', text)
        text = text.replace('jusqu\'à', '-')
        text = text.replace(' / ', ', ')
        text = re.sub(r'(\d):(\d{2})', r'\1:\2', text)
        text = re.sub(r'\s*-\s*', '-', text)
        text = re.sub(r'\s*,\s*', ', ', text)
        
        return text.strip()

    @retry_on_exception(retries=3, delay=5)
    def parse_opening_hours(self, element):
        """Parse opening hours for each day."""
        days = {
            'Lundi': 'Fermé', 
            'Mardi': 'Fermé', 
            'Mercredi': 'Fermé', 
            'Jeudi': 'Fermé',
            'Vendredi': 'Fermé', 
            'Samedi': 'Fermé', 
            'Dimanche': 'Fermé'
        }
        
        time_frames = element.find_elements(
            By.CSS_SELECTOR, 
            "li[data-cy='opening-hours-weekdays']"
        )
        
        for frame in time_frames:
            day = frame.find_element(
                By.CLASS_NAME, 
                "TimeFrame_day__3_oHv"
            ).text
            
            hours_element = frame.find_element(
                By.CSS_SELECTOR, 
                "div[itemprop='openingHours']"
            )
            hours = hours_element.text.strip()
            
            if day in days:
                days[day] = self.clean_time_text(hours)
                
        return days

    def clean_description(self, text):
        """Clean and format description text."""
        if not text:
            return ''
            
        text = re.sub(r'\n+', '\n', text)
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'<[^>]+>', '', text)
        
        return text.strip()

    def clean_list_text(self, text):
        """Clean and format list text."""
        if not text:
            return ''
            
        text = re.sub(r',\s*,', ',', text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip(',').strip()

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

    @retry_on_exception(retries=3, delay=5)
    def scrape_detail_page(self, url):
        """Scrape data from a detail page."""
        try:
            self.driver.get(url)
            
            # Wait for page to load with multiple possible selectors
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.CLASS_NAME, "detail_detail__SXBfi")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[data-cy='header-title']")),
                        EC.presence_of_element_located((By.CLASS_NAME, "DetailMapPreview_addressValue__pQROv"))
                    )
                )
            except TimeoutException:
                self.logger.warning(f"Page load timeout for {url}, trying to continue...")
                time.sleep(3)
                
        except Exception as e:
            self.logger.error(f"Error loading page {url}: {str(e)}")
            raise
        
        detail_data = {
            'url': url,
            'Title': '',  # This will be populated from the page title
            'Address': '',  # Full address string
            'logo_url': '',
            'title': '',
            'street': '',
            'zipcode': '',
            'city': '',
            'kanton': '',
            'phone_numbers': '',
            'email': '',
            'website': '',
            'description': '',
            'languages': '',
            'Lundi': 'Fermé',
            'Mardi': 'Fermé',
            'Mercredi': 'Fermé',
            'Jeudi': 'Fermé',
            'Vendredi': 'Fermé',
            'Samedi': 'Fermé',
            'Dimanche': 'Fermé'
        }
        
        # Get logo URL
        try:
            logo_img = self.driver.find_element(
                By.CSS_SELECTOR,
                ".DetailHeaderRow_logoContainer__kdz6N img"
            )
            detail_data['logo_url'] = logo_img.get_attribute('src')
        except NoSuchElementException:
            pass
        
        # Get title
        try:
            title = self.driver.find_element(
                By.CSS_SELECTOR,
                "[data-cy='header-title']"
            )
            title_text = title.text.strip()
            detail_data['title'] = title_text
            detail_data['Title'] = title_text  # Populate both fields
        except NoSuchElementException:
            pass
        
        # Get address
        try:
            address = self.driver.find_element(
                By.CLASS_NAME,
                "DetailMapPreview_addressValue__pQROv"
            )
            address_text = address.text.strip()
            street, zipcode, city, kanton = self.parse_address(address_text)
            detail_data.update({
                'Address': address_text,  # Full address string
                'street': street,
                'zipcode': zipcode,
                'city': city,
                'kanton': kanton
            })
        except NoSuchElementException:
            pass
        
        # Get opening hours
        try:
            hours_element = self.driver.find_element(
                By.CLASS_NAME,
                "OpeningHours_openingHoursBody__ApmXd"
            )
            opening_hours = self.parse_opening_hours(hours_element)
            detail_data.update(opening_hours)
        except NoSuchElementException:
            pass
        
        # Get contact information
        for contact_group in self.driver.find_elements(
            By.CLASS_NAME,
            "ContactGroupsAccordion_contactGroup__dsb2_"
        ):
            try:
                label = contact_group.find_element(
                    By.CLASS_NAME,
                    "ContactGroupsAccordion_contactType__8Y1ED"
                ).text.lower()
                
                value = contact_group.find_element(
                    By.CLASS_NAME,
                    "ContactGroupsAccordion_accordionGroupValue__lmVyw"
                ).text.strip()
                
                if 'téléphone' in label:
                    detail_data['phone_numbers'] = self.clean_list_text(value)
                elif 'e-mail' in label:
                    detail_data['email'] = value
                elif 'site web' in label:
                    detail_data['website'] = value
            except NoSuchElementException:
                continue
        
        # Get languages
        try:
            headers = self.driver.find_elements(
                By.CLASS_NAME,
                "DescriptionContent_detailListTitle__hIIB6"
            )
            
            languages_section = None
            for header in headers:
                if header.text.strip() == "Langues":
                    languages_section = header
                    break
            
            if languages_section:
                languages_dd = languages_section.find_element(
                    By.XPATH,
                    "./following-sibling::dd[1]"
                )
                
                language_spans = languages_dd.find_elements(
                    By.CLASS_NAME,
                    "DescriptionContent_detailListContentAttribute__zhs_H"
                )
                
                langs = [span.text.strip().rstrip(',') for span in language_spans]
                detail_data['languages'] = self.clean_list_text(', '.join(langs))
        except NoSuchElementException:
            pass
        
        # Get description
        try:
            description_element = self.driver.find_element(
                By.CSS_SELECTOR,
                "[data-cy='description-content']"
            )
            description_text = description_element.text.strip()
            detail_data['description'] = self.clean_description(description_text)
        except NoSuchElementException:
            # Try alternative selector for description
            try:
                description_element = self.driver.find_element(
                    By.CLASS_NAME,
                    "DescriptionContent_descriptionContent__zQqJz"
                )
                description_text = description_element.text.strip()
                detail_data['description'] = self.clean_description(description_text)
            except NoSuchElementException:
                pass
        
        return detail_data

    def scrape_from_links(self, csv_file):
        """Main function to scrape details from links in CSV."""
        try:
            # Load existing progress
            self.load_checkpoint()
            
            # Read all links
            df = pd.read_csv(csv_file)
            links = df['link'].tolist()
            total_links = len(links)
            
            self.logger.info(f"Starting to scrape {total_links} links")
            self.logger.info(f"Already processed: {len(self.processed_urls)} links")
            
            self.setup_driver()
            
            for i, link in enumerate(links, 1):
                if link in self.processed_urls:
                    self.logger.info(f"Skipping already processed link {i}/{total_links}: {link}")
                    continue
                    
                self.logger.info(f"Scraping detail page {i}/{total_links}: {link}")
                
                try:
                    detail_data = self.scrape_detail_page(link)
                    
                    if detail_data:
                        self.results.append(detail_data)
                        self.processed_urls.add(link)
                        
                        # Save checkpoint every 5 records
                        if len(self.results) % 5 == 0:
                            self.save_checkpoint()
                            self.logger.info(f"Checkpoint saved. Progress: {len(self.results)}/{total_links}")
                    
                except Exception as e:
                    self.logger.error(f"Error processing link {link}: {str(e)}")
                    # Save checkpoint on error
                    self.save_checkpoint()
                    continue
                
                # Random delay to avoid being blocked
                import random
                delay = random.uniform(1, 3)
                time.sleep(delay)
            
            # Final save and export
            self.save_checkpoint()
            self.export_to_excel('scraped_results.xlsx')
            self.logger.info(f"Scraping completed! Total records: {len(self.results)}")
            
        except Exception as e:
            self.logger.error(f"Error during scraping: {str(e)}")
            self.save_checkpoint()
            # Try to export partial results
            try:
                self.export_to_excel('scraped_results_partial.xlsx')
            except:
                pass
        finally:
            if self.driver:
                self.driver.quit()

def main():
    scraper = VetDetailScraper()
    scraper.scrape_from_links('veterinary_clinics.csv')

if __name__ == "__main__":
    main()
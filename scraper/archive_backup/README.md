# Local.ch Intelligent Web Scraper

A comprehensive web scraper for Local.ch that searches by keywords and performs credibility analysis on business listings.

## Features

### 1. Keyword-Based Search
- Automatically searches Local.ch based on any keyword (e.g., "plumber", "restaurant", "dentist")
- Scrapes all search result pages for the given keyword
- Collects company URLs automatically

### 2. Credibility Check
The scraper evaluates each company's credibility by checking:

#### Profile Completeness
- ✅ **Full Description**: Checks if company has a detailed description (100+ characters)
- ✅ **Pictures**: Counts the number of images in the company profile
- ✅ **Reviews**: Extracts and counts customer reviews
- ✅ **Contact Information**: Verifies presence of phone, email, and website
- ✅ **Social Media**: Detects links to Facebook, Instagram, Twitter, LinkedIn, YouTube
- ✅ **Complete Address**: Verifies street, postal code, city, and canton

#### Credibility Score (0-100)
The scraper calculates a credibility score based on:
- Description quality: 20 points
- Pictures: 20 points (5+ images = full points)
- Reviews: 20 points (10+ reviews = full points)
- Contact info: 20 points
- Social media: 10 points
- Complete address: 10 points

### 3. Website Analysis
For each company with a website, the scraper:

#### Local Search Detection
- ✅ Visits the company website
- ✅ Checks footer for "Local Search" mentions
- ✅ Examines legal/mentions pages for "Local Search" references
- ✅ Identifies if the site was created by Local Search

#### Website Age Estimation
- ✅ Extracts copyright year from website footer
- ✅ Helps identify recently created websites (e.g., 2026)
- ✅ Useful for sales targeting (avoid companies in long-term contracts)

## Data Fields Extracted

### Basic Information
- `url` - Company listing URL
- `keyword` - Search keyword used
- `title` - Business name
- `street` - Street address
- `zipcode` - Postal code
- `city` - City name
- `kanton` - Canton/state
- `logo_url` - Logo image URL

### Contact Information
- `phone_numbers` - Phone numbers
- `email` - Email address
- `website` - Website URL
- `languages` - Languages spoken

### Credibility Metrics
- `description` - Business description
- `picture_count` - Number of images (credibility indicator)
- `review_count` - Number of reviews (credibility indicator)
- `has_social_media` - Boolean: has social media presence
- `credibility_score` - Overall score (0-100)

### Website Analysis
- `has_local_search` - Boolean: website mentions "Local Search"
- `copyright_year` - Copyright year from website (e.g., "2024", "2026")

## Installation

1. Install required packages:
```bash
pip install -r requirements.txt
```

2. Make sure you have Chrome browser installed
3. ChromeDriver will be automatically managed by Selenium

## Usage

### Interactive Mode
```bash
python app.py
```

The script will prompt you for:
- Keyword to search (e.g., "plumber", "dentist", "restaurant")
- Maximum number of search pages to scrape

### Programmatic Usage
```python
from app import LocalChScraper

# Create scraper with keyword
scraper = LocalChScraper(keyword="plumber")

# Scrape up to 10 search result pages
scraper.scrape(max_search_pages=10)
```

## Output

The scraper generates:
- `{keyword}_scraped_results.xlsx` - Complete results in Excel format
- `scraping_checkpoint.csv` - Progress checkpoint (for resume capability)
- `scraping_log_YYYYMMDD_HHMMSS.log` - Detailed logging

## Advanced Features

### Checkpoint & Resume
- Automatically saves progress every 5 records
- Can resume scraping if interrupted
- Skips already processed URLs

### Anti-Detection
- Randomized delays between requests (2-4 seconds)
- Headless browser with anti-detection measures
- Custom user agents
- Exponential backoff on errors

### Error Handling
- Retry mechanism with exponential backoff (3 retries)
- Graceful handling of missing elements
- Partial results export on errors
- Comprehensive logging

## Use Cases

### Sales Team
Filter companies by credibility score to prioritize high-quality leads:
- **High credibility (80-100)**: Established businesses, good prospects
- **Medium credibility (50-79)**: Needs improvement, good upsell opportunity
- **Low credibility (0-49)**: New or incomplete profiles

### Avoid Recent Contracts
Use `copyright_year` to identify recently created websites:
- If `copyright_year == "2026"`, likely in a new contract → wait to contact
- If `has_local_search == True`, likely using Local Search services

### Target Analysis
Identify companies that:
- Have reviews but no website → upsell website creation
- Have website but no social media → upsell social media management
- Low picture count → upsell professional photography

## Technical Details

### Technology Stack
- **Selenium**: Web automation for JavaScript-heavy sites
- **BeautifulSoup**: HTML parsing for website analysis
- **Pandas**: Data manipulation and Excel export
- **Requests**: HTTP requests for website content

### Performance
- Processes approximately 1-2 companies per second
- Includes website visits for complete analysis
- Saves progress regularly to prevent data loss

## Troubleshooting

1. **ChromeDriver Issues**: Ensure Chrome browser is up to date
2. **Rate Limiting**: Scraper includes delays, but increase if needed
3. **Website Timeouts**: Some websites may be slow or unreachable (logged as warnings)
4. **Missing Data**: Some fields may be empty if not available on the profile

## Example Output

| title | credibility_score | review_count | picture_count | has_local_search | copyright_year |
|-------|-------------------|--------------|---------------|------------------|----------------|
| ABC Plumbing | 85 | 15 | 8 | True | 2023 |
| XYZ Services | 45 | 2 | 1 | False | 2026 |

## Ethical Considerations

- Respects robots.txt
- Uses reasonable delays between requests
- For business research and analysis purposes
- Complies with Local.ch terms of service

## Archive

Old versions of the scraper are stored in `archive_backup/` folder for reference.

#!/usr/bin/env python3
"""
Example usage of the Local.ch Intelligent Scraper
"""

from app import LocalChScraper

# Example 1: Scrape plumbers in Switzerland
def scrape_plumbers():
    print("=== Example 1: Scraping Plumbers ===")
    print("Initializing scraper...")
    scraper = LocalChScraper(keyword="plumber")
    print("Starting scrape (this may take 2-3 minutes for 5 companies)...")
    scraper.scrape(max_search_pages=1)  # Scrape first page only for testing
    print("Results saved to: plumber_scraped_results.xlsx\n")

# Example 2: Scrape restaurants
def scrape_restaurants():
    print("=== Example 2: Scraping Restaurants ===")
    scraper = LocalChScraper(keyword="restaurant")
    scraper.scrape(max_search_pages=1)  # Scrape first page only for testing
    print("Results saved to: restaurant_scraped_results.xlsx\n")

# Example 3: Scrape dentists
def scrape_dentists():
    print("=== Example 3: Scraping Dentists ===")
    scraper = LocalChScraper(keyword="dentist")
    scraper.scrape(max_search_pages=1)  # Scrape first page only for testing
    print("Results saved to: dentist_scraped_results.xlsx\n")

# Example 4: Custom keyword
def scrape_custom():
    print("=== Example 4: Custom Keyword ===")
    keyword = "veterinaire"  # or any other keyword
    scraper = LocalChScraper(keyword=keyword)
    scraper.scrape(max_search_pages=1)  # Scrape first page only for testing
    print(f"Results saved to: {keyword}_scraped_results.xlsx\n")

if __name__ == "__main__":
    # Uncomment the example you want to run

    scrape_plumbers()
    # scrape_restaurants()
    # scrape_dentists()
    # scrape_custom()

    print("✅ Scraping completed!")
    print("\nThe Excel file contains these credibility indicators:")
    print("  • credibility_score (0-100): Overall quality score")
    print("  • picture_count: Number of images on profile")
    print("  • review_count: Number of customer reviews")
    print("  • has_social_media: True/False for social media presence")
    print("  • has_local_search: True if website mentions 'Local Search'")
    print("  • copyright_year: Year from website (identify new contracts)")

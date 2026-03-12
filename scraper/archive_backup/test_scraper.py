#!/usr/bin/env python3
"""
Test script for the improved VetDetailScraper
"""

import sys
import os
from app import VetDetailScraper

def test_scraper():
    """Test the scraper with a small sample."""
    print("Testing VetDetailScraper...")
    
    # Create a test CSV with just a few URLs
    test_urls = [
        "https://www.local.ch/fr/d/geneve/1205/hygiene-dentaire-veterinaire",
        "https://www.local.ch/fr/d/geneve/1206/pharmacie-veterinaire"
    ]
    
    # Create test CSV
    import pandas as pd
    test_df = pd.DataFrame({
        'title': ['Test 1', 'Test 2'],
        'address': ['Test Address 1', 'Test Address 2'],
        'link': test_urls,
        'Word': ['Clinique vétérinaire', 'Clinique vétérinaire']
    })
    test_df.to_csv('test_veterinary_clinics.csv', index=False)
    
    # Test the scraper
    scraper = VetDetailScraper()
    
    try:
        print("Starting test scraping...")
        scraper.scrape_from_links('test_veterinary_clinics.csv')
        
        if scraper.results:
            print(f"Successfully scraped {len(scraper.results)} records")
            print("Sample record:")
            print(scraper.results[0])
        else:
            print("No results found")
            
    except Exception as e:
        print(f"Test failed: {str(e)}")
    finally:
        # Clean up test file
        if os.path.exists('test_veterinary_clinics.csv'):
            os.remove('test_veterinary_clinics.csv')

if __name__ == "__main__":
    test_scraper()

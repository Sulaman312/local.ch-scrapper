#!/usr/bin/env python3
"""
Flask Backend for Local.ch Scraper Dashboard
"""

from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_cors import CORS
from pymongo import MongoClient
from bson import ObjectId
from bson import json_util
from datetime import datetime
import sys
import os
import threading
import pandas as pd
from io import BytesIO
from dotenv import load_dotenv
import json

# Load environment variables from .env file
load_dotenv()

# Add scraper directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../scraper'))
from scraper import LocalChScraper

app = Flask(__name__)
CORS(app)

# MongoDB Connection
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(MONGO_URI)
db = client['localch_scraper']
jobs_collection = db['scrape_jobs']
companies_collection = db['companies']

# Active scraping threads
active_threads = {}

# Custom JSON encoder for Flask 3.0
from flask.json.provider import DefaultJSONProvider

class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

app.json = CustomJSONProvider(app)


def run_scraper_background(job_id, keyword, max_pages, max_companies, check_websites=False, check_moneyhouse=False, check_architectes=False, check_bienvivre=False):
    """Run scraper in background and save results to MongoDB"""
    try:
        # Update job status to running
        jobs_collection.update_one(
            {'_id': ObjectId(job_id)},
            {'$set': {'status': 'running', 'started_at': datetime.now()}}
        )

        # Create scraper instance
        scraper = LocalChScraper(
            keyword=keyword,
            check_websites=check_websites,
            check_moneyhouse=check_moneyhouse,
            check_architectes=check_architectes,
            check_bienvivre=check_bienvivre
        )

        # Setup driver first
        scraper.setup_driver()

        # Get total companies to scrape
        company_links = scraper.search_by_keyword(max_pages=max_pages)
        total_to_scrape = len(company_links)
        if max_companies and max_companies > 0:
            total_to_scrape = min(max_companies, total_to_scrape)

        # Update job with total expected companies
        jobs_collection.update_one(
            {'_id': ObjectId(job_id)},
            {'$set': {'total_companies': total_to_scrape, 'companies_scraped': 0}}
        )

        # Monkey-patch the scrape_detail_page method to save incrementally
        original_scrape_detail = scraper.scrape_detail_page

        def scrape_detail_with_save(url):
            # Run original scrape
            detail_data = original_scrape_detail(url)

            if detail_data:
                # Save to MongoDB immediately
                detail_data['job_id'] = ObjectId(job_id)
                detail_data['keyword'] = keyword
                detail_data['created_at'] = datetime.now()
                detail_data['status'] = 'new'
                detail_data['user_notes'] = ''
                companies_collection.insert_one(detail_data)

                # Update job progress
                companies_scraped = companies_collection.count_documents({'job_id': ObjectId(job_id)})
                jobs_collection.update_one(
                    {'_id': ObjectId(job_id)},
                    {'$set': {'companies_scraped': companies_scraped}}
                )

            return detail_data

        scraper.scrape_detail_page = scrape_detail_with_save

        # Now scrape the companies (we already have the links)
        # We need to manually iterate through company_links instead of calling scrape()
        if max_companies and max_companies > 0:
            max_companies_to_process = min(max_companies, len(company_links))
        else:
            max_companies_to_process = len(company_links)

        for i, link in enumerate(company_links[:max_companies_to_process], 1):
            if link in scraper.processed_urls:
                continue

            # Restart Chrome every 10 companies to prevent memory issues
            if i > 1 and (i - 1) % 10 == 0:
                scraper.logger.info(f"Restarting Chrome after {i - 1} companies to clear memory...")
                try:
                    if scraper.driver:
                        scraper.driver.quit()
                    import time
                    time.sleep(2)  # Wait for cleanup
                    scraper.setup_driver()
                    scraper.logger.info("Chrome restarted successfully")
                except Exception as e:
                    scraper.logger.error(f"Error restarting Chrome: {str(e)}")
                    # Try to continue anyway
                    pass

            scraper.logger.info(f"Scraping company {i}/{max_companies_to_process}: {link}")

            try:
                detail_data = scraper.scrape_detail_page(link)

                if detail_data:
                    scraper.results.append(detail_data)
                    scraper.processed_urls.add(link)

            except Exception as e:
                scraper.logger.error(f"Error processing link {link}: {str(e)}")
                continue

            # Random delay to avoid being blocked
            import random
            import time
            delay = random.uniform(1, 2)
            time.sleep(delay)

        # Final update - mark as completed
        companies_scraped = companies_collection.count_documents({'job_id': ObjectId(job_id)})
        jobs_collection.update_one(
            {'_id': ObjectId(job_id)},
            {
                '$set': {
                    'status': 'completed',
                    'completed_at': datetime.now(),
                    'total_companies': companies_scraped,
                    'companies_scraped': companies_scraped,
                    'progress': 100
                }
            }
        )

    except Exception as e:
        # Update job with error
        companies_scraped = companies_collection.count_documents({'job_id': ObjectId(job_id)})
        jobs_collection.update_one(
            {'_id': ObjectId(job_id)},
            {
                '$set': {
                    'status': 'failed',
                    'error_message': str(e),
                    'completed_at': datetime.now(),
                    'companies_scraped': companies_scraped
                }
            }
        )
    finally:
        # Close the driver
        if scraper and scraper.driver:
            scraper.driver.quit()
        # Remove from active threads
        if job_id in active_threads:
            del active_threads[job_id]


# ============= Routes =============

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')


@app.route('/results')
def results():
    """Results browser page"""
    return render_template('results.html')


# ============= API Endpoints =============

@app.route('/api/scrape/start', methods=['POST'])
def start_scrape():
    """Start a new scraping job"""
    data = request.json
    keyword = data.get('keyword', '').strip()
    max_pages = data.get('max_pages')
    if max_pages is not None:
        max_pages = int(max_pages)
    max_companies = data.get('max_companies')
    if max_companies is not None:
        max_companies = int(max_companies)
    check_websites = data.get('check_websites', False)
    check_moneyhouse = data.get('check_moneyhouse', False)
    check_architectes = data.get('check_architectes', False)
    check_bienvivre = data.get('check_bienvivre', False)

    if not keyword:
        return jsonify({'error': 'Keyword is required'}), 400

    # Create job record
    job = {
        'keyword': keyword,
        'max_pages': max_pages,
        'max_companies': max_companies,
        'check_websites': check_websites,
        'check_moneyhouse': check_moneyhouse,
        'check_architectes': check_architectes,
        'check_bienvivre': check_bienvivre,
        'status': 'pending',
        'progress': 0,
        'total_companies': 0,
        'companies_scraped': 0,
        'created_at': datetime.now(),
        'started_at': None,
        'completed_at': None,
        'error_message': None
    }

    result = jobs_collection.insert_one(job)
    job_id = str(result.inserted_id)

    # Start scraper in background thread
    thread = threading.Thread(
        target=run_scraper_background,
        args=(job_id, keyword, max_pages, max_companies, check_websites, check_moneyhouse, check_architectes, check_bienvivre)
    )
    thread.daemon = True
    thread.start()
    active_threads[job_id] = thread

    return jsonify({
        'success': True,
        'job_id': job_id,
        'message': 'Scraping job started'
    })


@app.route('/api/scrape/jobs', methods=['GET'])
def get_jobs():
    """Get all scraping jobs"""
    jobs = list(jobs_collection.find().sort('created_at', -1).limit(20))
    return jsonify(jobs)


@app.route('/api/scrape/jobs/<job_id>', methods=['GET'])
def get_job(job_id):
    """Get specific job details"""
    job = jobs_collection.find_one({'_id': ObjectId(job_id)})
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)


@app.route('/api/companies', methods=['GET'])
def get_companies():
    """Get companies with filters"""
    try:
        # Get filter parameters
        keyword = request.args.get('keyword')
        job_id = request.args.get('job_id')
        score_min = request.args.get('score_min', type=int)
        score_max = request.args.get('score_max', type=int)
        has_local_search = request.args.get('has_local_search')
        has_social_media = request.args.get('has_social_media')
        min_reviews = request.args.get('min_reviews', type=int)
        city = request.args.get('city')
        language = request.args.get('language')  # Comma-separated languages
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 25, type=int)

        # Build query
        query = {}
        if keyword:
            query['keyword'] = keyword
        if job_id:
            query['job_id'] = ObjectId(job_id)
        if score_min is not None:
            query['credibility_score'] = {'$gte': score_min}
        if score_max is not None:
            query.setdefault('credibility_score', {})['$lte'] = score_max
        if has_local_search is not None:
            query['has_local_search'] = has_local_search == 'true'
        if has_social_media is not None:
            query['has_social_media'] = has_social_media == 'true'
        if min_reviews is not None:
            query['review_count'] = {'$gte': min_reviews}
        if city:
            query['city'] = {'$regex': city, '$options': 'i'}
        if language:
            # Filter by any of the selected languages
            languages_list = [lang.strip() for lang in language.split(',')]
            query['languages'] = {'$in': languages_list}

        # Get total count
        total = companies_collection.count_documents(query)

        # Get paginated results
        skip = (page - 1) * per_page
        companies = list(
            companies_collection.find(query)
            .sort('credibility_score', -1)
            .skip(skip)
            .limit(per_page)
        )

        # Convert ObjectIds to strings and clean NaN values for JSON serialization
        import math
        for company in companies:
            if '_id' in company:
                company['_id'] = str(company['_id'])
            if 'job_id' in company:
                company['job_id'] = str(company['job_id'])

            # Replace NaN with None (null in JSON) or empty string
            for key, value in list(company.items()):
                if isinstance(value, float) and math.isnan(value):
                    # For numeric fields, use None; for string fields, use empty string
                    if 'count' in key or 'score' in key or 'rating' in key or 'year' in key:
                        company[key] = None
                    else:
                        company[key] = ''

        return jsonify({
            'companies': companies,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page
        })
    except Exception as e:
        print(f"Error in get_companies: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/companies/<company_id>', methods=['GET'])
def get_company(company_id):
    """Get specific company details"""
    company = companies_collection.find_one({'_id': ObjectId(company_id)})
    if not company:
        return jsonify({'error': 'Company not found'}), 404
    return jsonify(company)


@app.route('/api/companies/<company_id>/notes', methods=['PUT'])
def update_company_notes(company_id):
    """Update company notes and status"""
    data = request.json
    update_fields = {}

    if 'user_notes' in data:
        update_fields['user_notes'] = data['user_notes']
    if 'status' in data:
        update_fields['status'] = data['status']

    result = companies_collection.update_one(
        {'_id': ObjectId(company_id)},
        {'$set': update_fields}
    )

    if result.matched_count == 0:
        return jsonify({'error': 'Company not found'}), 404

    return jsonify({'success': True})


@app.route('/api/export', methods=['GET'])
def export_companies():
    """Export filtered companies to Excel"""
    # Get same filters as get_companies
    keyword = request.args.get('keyword')
    job_id = request.args.get('job_id')
    score_min = request.args.get('score_min', type=int)
    score_max = request.args.get('score_max', type=int)
    has_local_search = request.args.get('has_local_search')
    has_social_media = request.args.get('has_social_media')
    min_reviews = request.args.get('min_reviews', type=int)
    city = request.args.get('city')
    language = request.args.get('language')

    # Build query
    query = {}
    if keyword:
        query['keyword'] = keyword
    if job_id:
        query['job_id'] = ObjectId(job_id)
    if score_min is not None:
        query['credibility_score'] = {'$gte': score_min}
    if score_max is not None:
        query.setdefault('credibility_score', {})['$lte'] = score_max
    if has_local_search is not None:
        query['has_local_search'] = has_local_search == 'true'
    if has_social_media is not None:
        query['has_social_media'] = has_social_media == 'true'
    if min_reviews is not None:
        query['review_count'] = {'$gte': min_reviews}
    if city:
        query['city'] = {'$regex': city, '$options': 'i'}
    if language:
        languages_list = [lang.strip() for lang in language.split(',')]
        query['languages'] = {'$in': languages_list}

    # Get all matching companies (no pagination - export all filtered results)
    companies = list(companies_collection.find(query).sort('credibility_score', -1))

    # Get job keyword for filename if job_id provided
    export_name = keyword or 'all'
    if job_id and not keyword:
        job = jobs_collection.find_one({'_id': ObjectId(job_id)})
        if job:
            export_name = job.get('keyword', 'all')

    # Remove MongoDB _id and job_id for export
    for company in companies:
        company.pop('_id', None)
        company.pop('job_id', None)
        company.pop('created_at', None)

    # Create Excel file
    df = pd.DataFrame(companies)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Companies')
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'localch_export_{export_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@app.route('/api/scrape/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id):
    """Delete a job and all its associated companies"""
    try:
        job_object_id = ObjectId(job_id)

        # Delete all companies associated with this job
        companies_result = companies_collection.delete_many({'job_id': job_object_id})

        # Delete the job itself
        job_result = jobs_collection.delete_one({'_id': job_object_id})

        if job_result.deleted_count == 0:
            return jsonify({'error': 'Job not found'}), 404

        return jsonify({
            'success': True,
            'message': f'Deleted job and {companies_result.deleted_count} companies'
        })
    except Exception as e:
        print(f"Error deleting job: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get dashboard statistics"""
    keyword = request.args.get('keyword')
    query = {}
    if keyword:
        query['keyword'] = keyword

    total_companies = companies_collection.count_documents(query)

    # Average credibility score
    pipeline = [
        {'$match': query},
        {'$group': {'_id': None, 'avg_score': {'$avg': '$credibility_score'}}}
    ]
    avg_result = list(companies_collection.aggregate(pipeline))
    avg_score = avg_result[0]['avg_score'] if avg_result else 0

    # Companies by city (top 10)
    pipeline = [
        {'$match': query},
        {'$group': {'_id': '$city', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}},
        {'$limit': 10}
    ]
    cities = list(companies_collection.aggregate(pipeline))

    # Social media breakdown
    has_social = companies_collection.count_documents({**query, 'has_social_media': True})
    has_local_search = companies_collection.count_documents({**query, 'has_local_search': True})

    return jsonify({
        'total_companies': total_companies,
        'avg_credibility_score': round(avg_score, 1),
        'top_cities': cities,
        'has_social_media': has_social,
        'has_local_search': has_local_search
    })


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('FLASK_ENV') != 'production'
    app.run(debug=debug, host='0.0.0.0', port=port)

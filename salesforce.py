import os
import json
import glob
import logging
from datetime import datetime
from dotenv import load_dotenv
from simple_salesforce import Salesforce, SalesforceAuthenticationFailed

# -------------------------------------------------------------------
# Logging configuration
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()

sf_username = os.getenv("SALESFORCE_USERNAME")
sf_password = os.getenv("SALESFORCE_PASSWORD")
sf_security_token = os.getenv("SALESFORCE_SECURITY_TOKEN")

# Initialize Salesforce connection with error handling
sf = None
try:
    sf = Salesforce(username=sf_username, password=sf_password, security_token=sf_security_token)
    logger.info("Salesforce connection established successfully")
except SalesforceAuthenticationFailed as e:
    logger.error(f"Salesforce authentication failed: {e}")
except Exception as e:
    logger.error(f"Failed to connect to Salesforce: {e}")


def parse_date(date_str):
    """Parse date string in DD/MM/YYYY format to YYYY-MM-DD"""
    if not date_str:
        return None
    try:
        # Handle dates with relative time tags (e.g., '20/01/2026 - 3d')
        date_part = date_str.split(' - ')[0].strip()
        dt = datetime.strptime(date_part, "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError, IndexError) as e:
        logger.debug(f"Could not parse date '{date_str}': {e}")
        return None


def insert_company_growth_data(json_file_path):
    """
    Insert company growth data from JSON file into Salesforce.

    This function creates records using standard Salesforce objects:
    - Account: Main company record
    - Task: Individual articles and posts for each company

    Returns:
        str: Account ID on success
        None: On failure
    """
    if sf is None:
        logger.error("Salesforce connection not available, skipping insert")
        return None

    try:
        with open(json_file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.error(f"JSON file not found: {json_file_path}")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {json_file_path}: {e}")
        return None

    company_name = data.get('company', '')
    if not company_name:
        logger.warning(f"No company name found in {json_file_path}")
        return None

    try:
        # Check if account already exists (escape single quotes in company name)
        safe_company_name = company_name.replace("'", "\\'")
        existing_accounts = sf.query(f"SELECT Id FROM Account WHERE Name = '{safe_company_name}'")

        if existing_accounts['totalSize'] > 0:
            account_id = existing_accounts['records'][0]['Id']
            logger.info(f"Found existing account for {company_name} with ID: {account_id}")
        else:
            # Create the main company record as Account
            account_record = {
                'Name': company_name,
                'Description': f"Total Articles: {len(data.get('articles', []))}, Total Posts: {len(data.get('posts', []))}"
            }
            account_result = sf.Account.create(account_record)
            account_id = account_result['id']
            logger.info(f"Created account for {company_name} with ID: {account_id}")

        # Insert articles as Tasks
        article_count = 0
        article_errors = 0
        for article in data.get('articles', []):
            try:
                event_date = parse_date(article.get('date', ''))
                task_record = {
                    'Subject': f"Article: {article.get('headline', '')[:200]}",
                    'WhatId': account_id,
                    'Description': f"ARTICLE\n\nHeadline: {article.get('headline', '')}\n\nSummary: {article.get('summary', '')}\n\nGrowth Type: {article.get('growth_type', '')}\n\nSource: {article.get('source_url', '')}",
                    'ActivityDate': event_date,
                    'Status': 'Completed',
                    'Priority': 'Normal'
                }
                sf.Task.create(task_record)
                article_count += 1
            except Exception as e:
                article_errors += 1
                logger.warning(f"Failed to insert article for {company_name}: {e}")

        logger.info(f"Inserted {article_count} articles for {company_name} ({article_errors} errors)")

        # Insert posts as Tasks
        post_count = 0
        post_errors = 0
        for post in data.get('posts', []):
            try:
                event_date = parse_date(post.get('date', ''))
                task_record = {
                    'Subject': f"Post: {post.get('summary', '')[:200]}",
                    'WhatId': account_id,
                    'Description': f"POST\n\nSummary: {post.get('summary', '')}\n\nGrowth Type: {post.get('growth_type', '')}",
                    'ActivityDate': event_date,
                    'Status': 'Completed',
                    'Priority': 'Normal'
                }
                sf.Task.create(task_record)
                post_count += 1
            except Exception as e:
                post_errors += 1
                logger.warning(f"Failed to insert post for {company_name}: {e}")

        logger.info(f"Inserted {post_count} posts for {company_name} ({post_errors} errors)")

        return account_id

    except Exception as e:
        logger.exception(f"Error inserting data for {company_name}: {e}")
        return None


def insert_all_companies():
    """
    Insert all company JSON files from data/output directory.

    Returns:
        list: Results for each company with success/failure status
    """
    if sf is None:
        logger.error("Salesforce connection not available, cannot insert companies")
        return []

    json_files = glob.glob('data/output/*.json')

    logger.info(f"Found {len(json_files)} JSON files to process")

    results = []
    for json_file in json_files:
        logger.info(f"Processing {json_file}...")
        try:
            company_id = insert_company_growth_data(json_file)
            results.append({
                'file': json_file,
                'company_id': company_id,
                'success': company_id is not None
            })
        except Exception as e:
            logger.exception(f"Unexpected error processing {json_file}: {e}")
            results.append({
                'file': json_file,
                'company_id': None,
                'success': False
            })

    logger.info("=" * 50)
    logger.info("SUMMARY")
    logger.info("=" * 50)
    successful = sum(1 for r in results if r['success'])
    failed = len(results) - successful
    logger.info(f"Successfully inserted: {successful}/{len(results)} companies")
    if failed > 0:
        logger.warning(f"Failed: {failed} companies")

    return results


if __name__ == "__main__":
    insert_all_companies()

import os
import json
import glob
from datetime import datetime
from dotenv import load_dotenv
from simple_salesforce import Salesforce

load_dotenv()

sf_username = os.getenv("SALESFORCE_USERNAME")
sf_password = os.getenv("SALESFORCE_PASSWORD")
sf_security_token = os.getenv("SALESFORCE_SECURITY_TOKEN")

sf = Salesforce(username=sf_username, password=sf_password, security_token=sf_security_token)


def parse_date(date_str):
    """Parse date string in DD/MM/YYYY format to YYYY-MM-DD"""
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except:
        return None


def insert_company_growth_data(json_file_path):
    """
    Insert company growth data from JSON file into Salesforce.

    This function creates records using standard Salesforce objects:
    - Account: Main company record
    - Task: Individual articles and posts for each company
    """
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    company_name = data.get('company', '')

    try:
        # Check if account already exists
        existing_accounts = sf.query(f"SELECT Id FROM Account WHERE Name = '{company_name}'")

        if existing_accounts['totalSize'] > 0:
            account_id = existing_accounts['records'][0]['Id']
            print(f"Found existing account for {company_name} with ID: {account_id}")
        else:
            # Create the main company record as Account
            account_record = {
                'Name': company_name,
                'Description': f"Total Articles: {len(data.get('articles', []))}, Total Posts: {len(data.get('posts', []))}"
            }
            account_result = sf.Account.create(account_record)
            account_id = account_result['id']
            print(f"Created account for {company_name} with ID: {account_id}")

        # Insert articles as Tasks
        article_count = 0
        for article in data.get('articles', []):
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

        print(f"Inserted {article_count} articles for {company_name}")

        # Insert posts as Tasks
        post_count = 0
        for post in data.get('posts', []):
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

        print(f"Inserted {post_count} posts for {company_name}")

        return account_id

    except Exception as e:
        print(f"Error inserting data for {company_name}: {str(e)}")
        return None


def insert_all_companies():
    """Insert all company JSON files from data/output directory"""
    json_files = glob.glob('data/output/*.json')

    print(f"Found {len(json_files)} JSON files to process")

    results = []
    for json_file in json_files:
        print(f"\nProcessing {json_file}...")
        company_id = insert_company_growth_data(json_file)
        results.append({
            'file': json_file,
            'company_id': company_id,
            'success': company_id is not None
        })

    print("\n" + "="*50)
    print("SUMMARY")
    print("="*50)
    successful = sum(1 for r in results if r['success'])
    print(f"Successfully inserted: {successful}/{len(results)} companies")

    return results


if __name__ == "__main__":
    insert_all_companies()

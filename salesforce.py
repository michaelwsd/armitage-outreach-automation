import os 
import requests 
from dotenv import load_dotenv

load_dotenv()

domain = os.getenv("SALESFORCE_DOMAIN")

def get_access_token():
    payload = {
        'grant_type': 'client_credentials',
        'client_id': os.getenv('CONSUMER_KEY'),
        'client_secret': os.getenv('CONSUMER_SECRET')
    }

    oauth_endpoint = '/services/oauth2/token'
    response = requests.post(domain + oauth_endpoint, data=payload)
    return response.json()['access_token']

def get_dashboards(domain):
    access_token = get_access_token()
    print(access_token)
    url = f"{domain}/services/data/v62.0/analytics/dashboards"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    return response.json()


if __name__ == "__main__":
    dashboards = get_dashboards(domain)
    # for db in dashboards.get("dashboards", []):
        # print(db["name"], db["id"])
    print(dashboards)
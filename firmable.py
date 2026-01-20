import os 
import requests
from dotenv import load_dotenv

load_dotenv()

FIRMABLE_API_KEY = os.getenv("FIRMABLE_API_KEY")
BASE_URL = "https://api.firmable.com/company"

def get_info(company_url):
    headers = {
        "Authorization": f"Bearer {FIRMABLE_API_KEY}",
        "Accept": "application/json"
    }

    params = {
        "website": company_url
    }

    headers = {
        "Authorization": f"Bearer {FIRMABLE_API_KEY}"
    }

    response = requests.get(BASE_URL, headers=headers, params=params)
    response.raise_for_status()

    data = response.json()
    extracted = {
        "hq_location": data.get("hq_location"),
        "linkedin": data.get("linkedin"),
        "website": data.get("website"),
        "industry": data.get("industries")[0]
    }

    return extracted



if __name__ == "__main__":
    print(get_info("https://www.labgroup.com.au/"))
import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("CUSTOM_SEARCH_API_KEY")
CX_ID = os.getenv("CX_ID")

def get_company_url(company_name, location):
    base_url = "https://www.googleapis.com/customsearch/v1"
    
    # Construct a query that targets the homepage
    query = f"{company_name} {location} official site"
    
    params = {
        "key": API_KEY,
        "cx": CX_ID,
        "q": query,
        "num": 1  # We only need the top result
    }
    
    try:
        response = requests.get(base_url, params=params)
        response.raise_for_status()
        results = response.json()
        
        # Check if 'items' exists in the response
        if "items" in results:
            first_result = results["items"][0]
            link = first_result.get("link")
            return link
            return {
                "title": first_result.get("title"),
                "link": first_result.get("link"),
                "snippet": first_result.get("snippet")
            }
        else:
            return None
            
    except Exception as e:
        print(f"Error: {e}")
        return None
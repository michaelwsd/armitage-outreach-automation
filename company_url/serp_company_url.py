import os 
import serpapi
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("SERP_API_KEY")

def get_company_url(name, location):
  params = {
    "engine": "google",
    "location": "Australia",
    "google_domain": "google.com.au",
    "hl": "en",
    "gl": "au",
    "q": f"{name} {location}",
    "api_key": API_KEY
  }

  client = serpapi.Client(api_key=params["api_key"])
  results = client.search(params)
  return results["organic_results"][0]["link"]
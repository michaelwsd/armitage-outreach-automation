import os
import logging
import requests
from dotenv import load_dotenv

# -------------------------------------------------------------------
# Logging configuration
# -------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

load_dotenv()

FIRMABLE_API_KEY = os.getenv("FIRMABLE_API_KEY")
BASE_URL = "https://api.firmable.com/company"

def get_company_info(url, linkedin=False):
    """
    Get company information from Firmable API.

    Returns:
        dict: Company info with hq_location, linkedin, industry on success
        None: On any failure (API error, missing data, etc.)
    """
    if not url:
        logger.warning("No URL provided to get_company_info")
        return None

    headers = {
        "Authorization": f"Bearer {FIRMABLE_API_KEY}",
        "Accept": "application/json"
    }

    if linkedin:
        params = {"ln_url": url}
    else:
        params = {"website": url}

    try:
        response = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        # If the first attempt fails and URL doesn't end in .au, try with .com.au
        if not url.endswith('.au'):
            logger.info(f"First Firmable request failed for {url}, trying .com.au variant")
            # Replace or add .com.au suffix
            has_trailing_slash = url.endswith('/')
            base_url = url.rstrip('/')

            # Replace .com with .com.au to avoid .com.com.au
            if base_url.endswith('.com'):
                retry_url = base_url[:-4] + '.com.au'
            else:
                retry_url = base_url + '.com.au'

            if has_trailing_slash:
                retry_url += '/'

            if linkedin:
                params = {"ln_url": retry_url}
            else:
                params = {"website": retry_url}

            try:
                response = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
                response.raise_for_status()
            except requests.exceptions.RequestException as retry_e:
                logger.exception(f"Firmable API retry also failed for {retry_url}: {retry_e}")
                return None
        else:
            logger.exception(f"Firmable API error for {url}: {e}")
            return None

    try:
        data = response.json()

        # Safely extract data with defaults
        industries = data.get("industries", [])
        industry = industries[0] if industries else "Unknown"

        extracted = {
            "hq_location": data.get("hq_location"),
            "linkedin": data.get("linkedin"),
            "industry": industry
        }

        logger.info(f"Successfully retrieved company info for {url}")
        return extracted

    except (ValueError, IndexError, KeyError) as e:
        logger.exception(f"Error parsing Firmable response for {url}: {e}")
        return None

if __name__ == "__main__":
    print(get_company_info("https://www.lawinorder.com/"))
import os
import json
from datetime import datetime, timedelta
from openai import OpenAI
from dotenv import load_dotenv
from company_url import get_company_url
from firmable import get_info

load_dotenv()

client = OpenAI(
    api_key=os.getenv("PERPLEXITY_API_KEY"),
    base_url="https://api.perplexity.ai"
)

# Schema remains the same
article_schema = {
    "type": "json_schema",
    "json_schema": {
        "schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string"},
                "articles": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "headline": {"type": "string"},
                            "date": {"type": "string", "description": "Public date of the article in DD Month YYYY format"},
                            "summary": {"type": "string"},
                            "growth_type": {"type": "string"},
                            "source_url": {"type": "string"}
                        },
                        "required": ["headline", "date", "summary", "growth_type", "source_url"]
                    }
                }
            },
            "required": ["company", "articles"]
        }
    }
}

def pull_news(company_name, location):
    # Calculate the exact date one year ago for precision
    one_year_ago = (datetime.now() - timedelta(days=365)).strftime("%d %B %Y")

    company_url = get_company_url(company_name, location)

    print(f"company url: {company_url}")

    company_info = get_info(company_url)

    print(f"company info: {company_info}")
    print()

    # 1. COMPREHENSIVE SYSTEM PROMPT
    # We define a persona and strict data quality rules.
    system_prompt = (
        "You are a Senior Market Researcher. "
        "Your job is to research and find news articles of the company for the given time period, based on user requirement. "
        "You must output strictly valid JSON matching the provided schema."
    )

    # 2. COMPREHENSIVE USER PROMPT
    # We explicitly define what "Growth" means and what to IGNORE.
    user_prompt = (
        f"The company you will be finding news articles for is {company_name}. {company_name} is located at {company_info['hq_location']}, they are primarily in the {company_info['industry']} industries. "
        f"Find news articles indicating growth (awards, expansion, new hires, partnerships, patents, financial success, etc) for {company_name}, prioritize the company linkedin page 'www.linkedin.com/company/{company_info['linkedin']}' and the company website {company_info['website']}, but also look into other reliable news sources. "
        f"Focus strictly on events after {one_year_ago}"
    )

    print(user_prompt)

    try:
        response = client.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format=article_schema,
            extra_body={
                "return_citations": True
            }
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        print(json.dumps(data, indent=2))

    except Exception as e:
        print(f"Error: {e}")

# Run the function
if __name__ == "__main__":
    pull_news("GRC Solutions", "Sydney")
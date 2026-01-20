import json
from datetime import datetime 

# 1. Load the data
with open('res.json', 'r') as file:
    data = json.load(file)

# Parse date string → datetime
def parse_date(article):
    return datetime.strptime(article["date"], "%d %B %Y")

# Sort articles (newest first)
data["articles"] = sorted(
    data["articles"],
    key=parse_date,
    reverse=True
)

print(json.dumps(data, indent=2))
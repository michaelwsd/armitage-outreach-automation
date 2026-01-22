import os 
import pandas as pd 
from dotenv import load_dotenv
from simple_salesforce import Salesforce

load_dotenv()

sf_username = os.getenv("SALESFORCE_USERNAME")
sf_password = os.getenv("SALESFORCE_PASSWORD")
sf_security_token = os.getenv("SALESFORCE_SECURITY_TOKEN")

sf = Salesforce(sf_username, sf_password, sf_security_token)



from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON
import os
from dotenv import load_dotenv

load_dotenv()

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=POLYGON,
    key=os.getenv("PRIVATE_KEY"),
    signature_type=2,
    funder=os.getenv("FUNDER_ADDRESS"),
)

creds = client.create_api_key()
print("=" * 50)
print("API_KEY:", creds.api_key)
print("API_SECRET:", creds.api_secret)
print("API_PASSPHRASE:", creds.api_passphrase)
print("=" * 50)

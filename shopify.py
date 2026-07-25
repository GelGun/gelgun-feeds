"""Minimal read-only Shopify Admin API client for feed generation.
Credentials come from env (SHOPIFY_SHOP / SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET)."""
import os, time, requests
from dotenv import load_dotenv
load_dotenv()
SHOP = os.getenv("SHOPIFY_SHOP")
CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")
BASE_URL = f"https://{SHOP}.myshopify.com"
_token_cache = {"access_token": None, "expires_at": 0}

def _get_access_token():
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 300:
        return _token_cache["access_token"]
    r = requests.post(f"{BASE_URL}/admin/oauth/access_token",
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={"grant_type": "client_credentials",
                            "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET})
    r.raise_for_status(); d = r.json()
    _token_cache["access_token"] = d["access_token"]
    _token_cache["expires_at"] = time.time() + d.get("expires_in", 86399)
    return _token_cache["access_token"]

def _shopify_get(path, params=None):
    token = _get_access_token()
    r = requests.get(f"{BASE_URL}/admin/api/2025-01{path}",
                     headers={"X-Shopify-Access-Token": token}, params=params or {})
    r.raise_for_status(); return r.json()

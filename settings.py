"""Secrets and settings lookup.

Order: Streamlit secrets (Streamlit Community Cloud's Secrets panel, or .streamlit/secrets.toml),
then config.toml in the project root (local runs; git-ignored), then environment variables.
Keys match case-insensitively, so `nebius_api_key` and `NEBIUS_API_KEY` both work.
"""
import os
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

LOCAL_SECRETS_FILE = Path(__file__).resolve().parent / "config.toml"

@lru_cache(maxsize=1)
def _local_toml() -> Dict[str, Any]:
    if not LOCAL_SECRETS_FILE.exists():
        return {}
    with open(LOCAL_SECRETS_FILE, "rb") as f:
        return {k.lower(): v for k, v in tomllib.load(f).items()}

def _streamlit_secret(name: str) -> Optional[Any]:
    try:
        import streamlit as st
        for key in (name.lower(), name.upper()):
            if key in st.secrets:
                return st.secrets[key]
    except Exception:
        # No secrets file configured, or not running under Streamlit
        pass
    return None

def get_setting(name: str, default: Optional[Any] = None) -> Optional[Any]:
    for value in (_streamlit_secret(name), _local_toml().get(name.lower()), os.getenv(name.upper())):
        if value not in (None, ""):
            return value
    return default

import os
import json
import threading
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
KEYS_FILE = BASE_DIR / "api_keys.json"

_lock = threading.Lock()

_ENV_MAP = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _load() -> dict:
    data = {}
    try:
        if KEYS_FILE.exists():
            data = json.loads(KEYS_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[API KEYS] Read error: {e}")
        data = {}

    # Backward compat: seed from .env if provider has no stored keys
    for provider, envvar in _ENV_MAP.items():
        if not data.get(provider):
            envval = os.getenv(envvar, "")
            if envval:
                data[provider] = [k.strip() for k in envval.split(",") if k.strip()]

    for provider in _ENV_MAP:
        if not isinstance(data.get(provider), list):
            data[provider] = []
    return data


def _save(data: dict):
    tmp = KEYS_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, KEYS_FILE)
    except Exception as e:
        print(f"[API KEYS] Write error: {e}")


def get_keys(provider: str) -> list:
    provider = (provider or "groq").lower()
    with _lock:
        return list(_load().get(provider, []))


def get_all_keys() -> dict:
    with _lock:
        return _load()


def add_key(provider: str, key: str) -> list:
    provider = (provider or "groq").lower()
    key = (key or "").strip()
    if not key:
        raise ValueError("Key is empty")
    with _lock:
        data = _load()
        keys = data.get(provider, [])
        if key not in keys:
            keys.append(key)
        data[provider] = keys
        _save(data)
        return list(keys)


def remove_key(provider: str, index: int) -> list:
    provider = (provider or "groq").lower()
    with _lock:
        data = _load()
        keys = data.get(provider, [])
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = -1
        if 0 <= index < len(keys):
            keys.pop(index)
        data[provider] = keys
        _save(data)
        return list(keys)


def set_keys(provider: str, keys: list) -> list:
    provider = (provider or "groq").lower()
    with _lock:
        data = _load()
        data[provider] = [k.strip() for k in (keys or []) if k.strip()]
        _save(data)
        return list(data[provider])


def mask_key(key: str) -> str:
    key = key or ""
    if len(key) <= 8:
        return "***"
    return f"{key[:5]}...{key[-4:]}"


def masked_keys(provider: str) -> list:
    return [mask_key(k) for k in get_keys(provider)]

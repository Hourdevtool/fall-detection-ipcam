import random
import string
import time
import uuid
import os
import json

SYSTEM_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "system_config.json")


def _load_config() -> dict:
    """Load configuration from system_config.json."""
    config_path = os.path.abspath(SYSTEM_CONFIG_PATH)
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_config(config: dict):
    """Save configuration to system_config.json."""
    config_path = os.path.abspath(SYSTEM_CONFIG_PATH)
    config_dir = os.path.dirname(config_path)
    if not os.path.exists(config_dir):
        os.makedirs(config_dir, exist_ok=True)
        
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def get_or_create_system_id() -> str:
    """
    Get or create a persistent system ID.
    This identifies THIS detection system instance.
    Stored in system_config.json so it persists across restarts.
    """
    config = _load_config()
    if "system_id" in config:
        return config["system_id"]

    # Generate new system ID
    system_id = uuid.uuid4().hex[:8]
    config["system_id"] = system_id
    _save_config(config)

    print(f"🆔 Generated new system ID: {system_id}")
    return system_id


def generate_pair_code() -> str:
    """Generate a random 6-digit numeric pairing code."""
    return "".join(random.choices(string.digits, k=6))


def create_new_pair_code(system_id: str, expires_in: int = 600) -> dict:
    """
    Create or retrieve a persistent pairing code.
    (We ignore expires_in and keep the code persistent)
    """
    config = _load_config()
    if "pair_code" in config:
        code = config["pair_code"]
    else:
        code = generate_pair_code()
        config["pair_code"] = code
        _save_config(config)

    entry = {
        "code": code,
        "system_id": system_id,
        "created_at": time.time(),
        "expires_at": 2147483647,  # Never expires
        "expires_in": 2147483647,
    }
    return entry


def validate_pair_code(code: str) -> dict | None:
    """
    Validate a pairing code against the persistent config.
    Returns the entry if valid, None if invalid.
    Does NOT consume the code (persistent).
    """
    config = _load_config()
    stored_code = config.get("pair_code")
    system_id = config.get("system_id")

    if stored_code and stored_code == code and system_id:
        return {
            "code": stored_code,
            "system_id": system_id,
            "created_at": time.time(),
            "expires_at": 2147483647,
            "expires_in": 2147483647,
        }
    return None


def get_current_pair_code(system_id: str) -> dict | None:
    """Get the current persistent pairing code for this system."""
    config = _load_config()
    stored_code = config.get("pair_code")
    
    if not stored_code:
        return create_new_pair_code(system_id)
        
    if config.get("system_id") == system_id:
        return {
            "code": stored_code,
            "system_id": system_id,
            "created_at": time.time(),
            "expires_at": 2147483647,
            "expires_in": 2147483647,
        }
    return None

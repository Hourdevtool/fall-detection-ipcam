import random
import string
import time
import uuid
import os
import json

SYSTEM_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "system_config.json")


def get_or_create_system_id() -> str:
    """
    Get or create a persistent system ID.
    This identifies THIS detection system instance.
    Stored in system_config.json so it persists across restarts.
    """
    config_path = os.path.abspath(SYSTEM_CONFIG_PATH)

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                if "system_id" in config:
                    return config["system_id"]
        except Exception:
            pass

    # Generate new system ID
    system_id = uuid.uuid4().hex[:8]

    config = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            pass

    config["system_id"] = system_id

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

    print(f"🆔 Generated new system ID: {system_id}")
    return system_id


def generate_pair_code() -> str:
    """Generate a random 6-digit numeric pairing code."""
    return "".join(random.choices(string.digits, k=6))


# ── In-memory active pairing codes (simple approach) ──

_active_codes: dict[str, dict] = {}


def create_new_pair_code(system_id: str, expires_in: int = 600) -> dict:
    """
    Create a new pairing code that expires in `expires_in` seconds.
    Returns {code, system_id, expires_at, expires_in}.
    """
    # Clean up expired codes
    now = time.time()
    expired = [c for c, v in _active_codes.items() if v["expires_at"] < now]
    for c in expired:
        del _active_codes[c]

    # Generate unique code
    code = generate_pair_code()
    while code in _active_codes:
        code = generate_pair_code()

    entry = {
        "code": code,
        "system_id": system_id,
        "created_at": now,
        "expires_at": now + expires_in,
        "expires_in": expires_in,
    }
    _active_codes[code] = entry
    print(f"🔗 Pairing code generated: {code} (expires in {expires_in}s)")
    return entry


def validate_pair_code(code: str) -> dict | None:
    """
    Validate a pairing code. Returns the entry if valid, None if invalid/expired.
    Consumes the code (one-time use).
    """
    now = time.time()

    if code not in _active_codes:
        return None

    entry = _active_codes[code]
    if entry["expires_at"] < now:
        del _active_codes[code]
        return None

    # Consume the code
    del _active_codes[code]
    return entry


def get_current_pair_code(system_id: str) -> dict | None:
    """Get the current active (non-expired) pairing code for this system."""
    now = time.time()
    for code, entry in _active_codes.items():
        if entry["system_id"] == system_id and entry["expires_at"] > now:
            remaining = int(entry["expires_at"] - now)
            return {**entry, "expires_in": remaining}
    return None

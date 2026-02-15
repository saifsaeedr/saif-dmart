"""
Test user OTP plugin: fixed OTP for configured MSISDNs (e.g. App Store / Play Store review accounts).
Listens to OTP requests by wrapping send_otp; for configured MSISDNs stores the fixed_otp from config
in the DB and skips SMS. Login then uses the stored code as usual.
"""
import json
from pathlib import Path

from models.core import PluginBase, Event


def _get_config() -> tuple[set[str], str] | None:
    config_path = Path(__file__).resolve().parent / "config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not data.get("is_active") or not data.get("msisdns") or not data.get("fixed_otp"):
        return None
    return (set(data["msisdns"]), data["fixed_otp"])


def _apply_patches() -> None:
    from api.user import service as user_service
    from api.user import router as router_module
    from data_adapters.adapter import data_adapter as db

    _original_send_otp = user_service.send_otp

    async def _send_otp_wrapper(msisdn: str, language: str):
        config = _get_config()
        if config and msisdn in config[0]:
            await db.save_otp(f"users:otp:otps/{msisdn}", config[1])
            return {"status": "success", "data": {"status": "success"}}
        return await _original_send_otp(msisdn, language)

    user_service.send_otp = _send_otp_wrapper
    router_module.send_otp = _send_otp_wrapper

class Plugin(PluginBase):
    """Hook plugin: on load, patches OTP flow so configured MSISDNs use fixed OTP."""

    async def hook(self, data: Event) -> None:
        pass

#plgin will work in mock and api mode
_apply_patches()

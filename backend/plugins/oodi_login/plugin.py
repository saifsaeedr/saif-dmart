"""
Oodi login plugin: when login has identifier (msisdn or shortname) + (otp or password),
first try to resolve/match using oodi number in user payload.body. If found, use that flow;
otherwise fall back to original flow.
- Password + msisdn (oodi): rewrite to shortname + password.
- OTP + msisdn (oodi): pass through (get_shortname_from_identifier resolves via payload body; OTP key = msisdn).
- OTP + shortname: pass through; send_otp is patched to store OTP under shortname when msisdn is oodi.
"""
import json
from pathlib import Path

from models.core import PluginBase, Event


def _get_config() -> dict | None:
    config_path = Path(__file__).resolve().parent / "config.json"
    if not config_path.exists():
        return None
    try:
        with open(config_path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not data.get("is_active"):
        return None
    return data


def _msisdn_from_body(body: dict) -> str | None:
    if not body or not isinstance(body, dict):
        return None
    msisdn = body.get("msisdn")
    if msisdn is not None and msisdn != "":
        return str(msisdn).strip() or None
    return None


def _shortname_from_body(body: dict) -> str | None:
    if not body or not isinstance(body, dict):
        return None
    s = body.get("shortname")
    if s is not None and s != "":
        return str(s).strip() or None
    return None


QUERY_USER = "dmart"
OODI_NUMBER_FIELD = "oodi_number"


async def _resolve_shortname_by_oodi_in_body(identifier_value: str, by_shortname: bool = False) -> str | None:
    """
    Find a user by oodi number in payload.body (field oodi_number, query_user dmart).
    If by_shortname=True: load user by shortname and return it if payload.body has oodi_number.
    If by_shortname=False: search users where payload.body.oodi_number = identifier_value.
    """
    from data_adapters.adapter import data_adapter as db
    from utils.settings import settings
    import models.api as api
    import models.core as core

    if by_shortname:
        user = await db.load_or_none(settings.management_space, "/users", identifier_value, core.User)
        if not user:
            return None
        payload_body = getattr(getattr(user, "payload", None), "body", None)
        if isinstance(payload_body, dict) and payload_body.get(OODI_NUMBER_FIELD):
            return identifier_value
        return None

    try:
        search_value = identifier_value.replace("\\", "\\\\").replace('"', '\\"')
        search = f"@payload.body.{OODI_NUMBER_FIELD}:{search_value}"
        query = api.Query(
            type=api.QueryType.search,
            space_name=settings.management_space,
            subpath="/users",
            search=search,
            limit=1,
            offset=0,
            retrieve_json_payload=False,
        )
        total, records = await db.query(query, QUERY_USER)
        if total and records:
            return records[0].shortname
        return None
    except Exception:
        return None


class _OodiLoginMiddleware:
    """For POST /user/login: if identifier (msisdn or shortname) + (otp or password), try oodi-in-body first; else original flow."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")
        if method != "POST" or path != "/user/login":
            await self.app(scope, receive, send)
            return

        if not _get_config():
            await self.app(scope, receive, send)
            return

        body_chunks = []
        while True:
            message = await receive()
            body_chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        body_bytes = b"".join(body_chunks)

        try:
            data = json.loads(body_bytes)
        except (json.JSONDecodeError, TypeError):
            async def _receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            await self.app(scope, _receive, send)
            return

        has_otp = data.get("otp") is not None and data.get("otp") != ""
        has_password = data.get("password") is not None and data.get("password") != ""
        if not (has_otp or has_password):
            # No otp/password: pass through unchanged
            async def _receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}
            await self.app(scope, _receive, send)
            return

        msisdn_value = _msisdn_from_body(data)
        shortname_value = _shortname_from_body(data)

        shortname = None
        if msisdn_value is not None:
            shortname = await _resolve_shortname_by_oodi_in_body(msisdn_value, by_shortname=False)
        elif shortname_value is not None:
            shortname = await _resolve_shortname_by_oodi_in_body(shortname_value, by_shortname=True)

        if shortname and msisdn_value is not None and not has_otp:
            # Password login with msisdn (oodi): rewrite to shortname so only one identifier
            data = dict(data)
            data.pop("msisdn", None)
            data["shortname"] = shortname
            body_bytes = json.dumps(data).encode("utf-8")

        async def _receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        await self.app(scope, _receive, send)


def _apply_patches() -> None:
    from api.user import service as user_service
    from api.user import router as user_router
    from data_adapters.adapter import data_adapter as db
    import models.api as api

    _original_get_shortname = user_service.get_shortname_from_identifier

    async def _get_shortname_wrapper(*args, **kwargs):
        key = kwargs.get("key", args[0] if args else None)
        value = kwargs.get("value", args[1] if len(args) > 1 else None)
        try:
            return await _original_get_shortname(*args, **kwargs)
        except api.Exception as e:
            if key != "msisdn" or not value:
                raise
            if getattr(e, "status_code", None) not in (404, 401):
                raise
            if not _get_config():
                raise
            shortname = await _resolve_shortname_by_oodi_in_body(str(value).strip(), by_shortname=False)
            if shortname:
                return shortname
            raise

    user_service.get_shortname_from_identifier = _get_shortname_wrapper
    # Router imports get_shortname_from_identifier at load time — patch its reference too (like send_otp in OTP plugin)
    user_router.get_shortname_from_identifier = _get_shortname_wrapper

    # When OTP is requested for an msisdn that is an oodi number (in payload body), also store OTP under shortname
    # so that login with shortname + otp finds the OTP.
    _original_send_otp = user_service.send_otp

    async def _send_otp_wrapper(msisdn: str, language: str):
        result = await _original_send_otp(msisdn, language)
        if not _get_config():
            return result
        shortname = await _resolve_shortname_by_oodi_in_body(msisdn.strip(), by_shortname=False)
        if shortname:
            try:
                code = await db.get_otp(f"users:otp:otps/{msisdn}")
                if code:
                    await db.save_otp(f"users:otp:otps/{shortname}", code)
            except Exception:
                pass
        return result

    user_service.send_otp = _send_otp_wrapper

    app = globals().get("app")
    if app is None:
        return
    app.add_middleware(_OodiLoginMiddleware)


class Plugin(PluginBase):
    """Hook plugin: login by msisdn or shortname + otp/password uses oodi number in payload.body first, else original flow."""

    async def hook(self, data: Event) -> None:
        pass


_apply_patches()

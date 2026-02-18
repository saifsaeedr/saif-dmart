"""
Oodi login plugin: for login with "msisdn" in the body, first checks if that value exists
in any user's payload.body; if yes, rewrites the request to use that user's shortname so
login proceeds. If not found in payload body, the regular login flow runs (msisdn as usual).
Uses ASGI middleware to rewrite the request body when a user is found by payload body.
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
    """Get msisdn from request body (top-level only; field name stays msisdn)."""
    if not body or not isinstance(body, dict):
        return None
    msisdn = body.get("msisdn")
    if msisdn is not None and msisdn != "":
        return str(msisdn).strip() or None
    return None


async def _resolve_shortname_by_payload_body_msisdn(msisdn_value: str, config: dict) -> str | None:
    """
    Find a user whose payload.body contains this msisdn value (e.g. payload.body.msisdn).
    Uses db.query with search on payload.body.<payload_field>; if no result, returns None
    so the regular login flow runs. Does not use get_user_by_criteria(msisdn) (user attribute).
    """
    from data_adapters.adapter import data_adapter as db
    from utils.settings import settings
    import models.api as api

    # payload_field = (config or {}).get("payload_body_msisdn_field") or "msisdn"
    # query_user = (config or {}).get("query_user")

    try:
        # Search users by payload.body.<payload_field> = msisdn_value (not user's msisdn column)
        search_value = msisdn_value.replace("\\", "\\\\").replace('"', '\\"')
        search = f'@payload.body.oodi_number:{search_value}'
        query = api.Query(
            type=api.QueryType.search,
            space_name=settings.management_space,
            subpath="/users",
            search=search,
            limit=1,
            offset=0,
            retrieve_json_payload=False,
        )
        total, records = await db.query(query, "dmart")
        print(f"this is the records: {records}")
        if total and records and len(records) > 0:
            shortname = records[0].shortname
            print(f"this is the shortname: {shortname}")
            return shortname
        return None
    except Exception:
        return None


class _OodiLoginMiddleware:
    """ASGI middleware: for POST /user/login with msisdn, rewrite to shortname when that msisdn exists in a user's payload.body."""

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

        config = _get_config()
        if not config:
            await self.app(scope, receive, send)
            return

        # Consume body (only once)
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

        # Field name stays "msisdn"; first check if it exists in any user's payload body
        msisdn_value = _msisdn_from_body(data)
        if msisdn_value is not None:
            shortname = await _resolve_shortname_by_payload_body_msisdn(msisdn_value, config)
            if shortname:
                # Rewrite body so login receives only shortname (one identifier; remove msisdn to avoid "Too many input")
                data = dict(data)
                data.pop("msisdn", None)
                data["shortname"] = shortname
                body_bytes = json.dumps(data).encode("utf-8")

        async def _receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        await self.app(scope, _receive, send)


def _apply_patches() -> None:
    app = globals().get("app")
    if app is None:
        return
    app.add_middleware(_OodiLoginMiddleware)
    print("hey i ran --------------------------")


class Plugin(PluginBase):
    """Hook plugin: on load, adds middleware so msisdn in body can resolve via user payload.body first."""

    async def hook(self, data: Event) -> None:
        pass

_apply_patches()

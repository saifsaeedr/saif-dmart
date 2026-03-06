"""
Plugin: email_order_update

Sends an email to the ticket owner when an order's state is updated to one of:
confirmed, delivered, refunded.

Listens to: /order/{any_sellers_folder}/{anyentry} (any ticket under a path starting with "order/")
"""

from fastapi.logger import logger
from models.core import PluginBase, Event, Ticket, User
from models.enums import ResourceType
from data_adapters.adapter import data_adapter as db
from utils.settings import settings
from api.user.service import send_email

# ---------------------------------------------------------------------------
# Editable: state-specific email body (HTML). Use {ticket_shortname} as placeholder.
# Subject line for each state can also be edited below.
# ---------------------------------------------------------------------------

STATE_EMAIL_MESSAGES = {
    "confirmed": (
        "<p>Your order has been confirmed.</p>"
        "<p>Order ID: <strong>{ticket_shortname}</strong></p>"
    ),
    "delivered": (
        "<p>Your order has been delivered.</p>"
        "<p>Order ID: <strong>{ticket_shortname}</strong></p>"
    ),
    "refunded": (
        "<p>Your order has been refunded.</p>"
        "<p>Order ID: <strong>{ticket_shortname}</strong></p>"
    ),
}

STATE_EMAIL_SUBJECTS = {
    "confirmed": "Order confirmed – {ticket_shortname}",
    "delivered": "Order delivered – {ticket_shortname}",
    "refunded": "Order refunded – {ticket_shortname}",
}

# Subpath prefix we listen to: /order(s)/{any_sellers_folder}/anyentry
ORDER_SUBPATH_PREFIXES = ("order/", "orders/")

# Only these states trigger an email
NOTIFY_STATES = frozenset({"confirmed", "delivered", "refunded"})


class Plugin(PluginBase):
    async def hook(self, event: Event) -> None:
        if event.resource_type != ResourceType.ticket:
            return

        subpath = (event.subpath or "").strip("/")
        if not any(subpath.startswith(p) for p in ORDER_SUBPATH_PREFIXES):
            return

        state = event.attributes.get("state") if event.attributes else None
        if not state or state not in NOTIFY_STATES:
            return

        ticket_shortname = event.shortname
        if not ticket_shortname:
            return

        try:
            ticket = await db.load(
                space_name=event.space_name,
                subpath=event.subpath,
                shortname=ticket_shortname,
                class_type=Ticket,
                user_shortname=event.user_shortname,
            )
        except Exception as e:
            logger.warning(
                "email_order_update: could not load ticket %s in %s: %s",
                ticket_shortname,
                event.subpath,
                e,
            )
            return

        owner_shortname = getattr(ticket, "owner_shortname", None)
        if not owner_shortname:
            logger.warning(
                "email_order_update: ticket %s has no owner_shortname",
                ticket_shortname,
            )
            return

        try:
            user = await db.load(
                space_name=settings.management_space,
                subpath="users",
                shortname=owner_shortname,
                class_type=User,
                user_shortname=owner_shortname,
            )
        except Exception as e:
            logger.warning(
                "email_order_update: could not load owner %s: %s",
                owner_shortname,
                e,
            )
            return

        email = getattr(user, "email", None)
        if not email:
            logger.warning(
                "email_order_update: owner %s has no email, skipping notification",
                owner_shortname,
            )
            return

        body_template = STATE_EMAIL_MESSAGES.get(state)
        subject_template = STATE_EMAIL_SUBJECTS.get(state)
        if not body_template or not subject_template:
            return

        body = body_template.format(ticket_shortname=ticket_shortname)
        subject = subject_template.format(ticket_shortname=ticket_shortname)

        logger.info(
            "email_order_update: sending %s email for order %s to %s (mock=%s)",
            state,
            ticket_shortname,
            email,
            getattr(settings, "mock_smtp_api", True),
        )
        await send_email(email, body, subject)
        logger.info(
            "email_order_update: sent %s email for order %s to %s",
            state,
            ticket_shortname,
            email,
        )

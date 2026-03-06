"""
Plugin: firebase_order_update

Sends a Firebase push notification (mobile) to the ticket owner when an order's
state is updated to one of: confirmed, delivered, refunded.

Listens to: /order/{any_sellers_folder}/{anyentry} (any ticket under a path starting with "order/").
"""

from fastapi.logger import logger

from data_adapters.adapter import data_adapter as db
from models.core import Event, NotificationData, PluginBase, Ticket, Translation, User
from models.enums import ResourceType
from utils.notification import NotificationManager
from utils.settings import settings

# Subpath prefix we listen to: /order(s)/{any_sellers_folder}/anyentry
ORDER_SUBPATH_PREFIXES = ("order/", "orders/")

# Only these states trigger a push notification
NOTIFY_STATES = frozenset({"confirmed", "delivered", "refunded"})


class Plugin(PluginBase):
    async def hook(self, event: Event) -> None:
        print("HEY I'M HERE ------------------------------------")
        if event.resource_type != ResourceType.ticket:
            return

        subpath = (event.subpath or "").strip("/")
        if not any(subpath.startswith(prefix) for prefix in ORDER_SUBPATH_PREFIXES):
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
        except Exception as exc:
            logger.warning(
                "firebase_order_update: could not load ticket %s in %s: %s",
                ticket_shortname,
                event.subpath,
                exc,
            )
            return

        owner_shortname = getattr(ticket, "owner_shortname", None)
        if not owner_shortname:
            logger.warning(
                "firebase_order_update: ticket %s has no owner_shortname",
                ticket_shortname,
            )
            return

        # Do not notify if the actor is the owner and you consider that redundant.
        if owner_shortname == event.user_shortname:
            return

        try:
            user = await db.load(
                space_name=settings.management_space,
                subpath=settings.users_subpath,
                shortname=owner_shortname,
                class_type=User
            )
        except Exception as exc:
            logger.warning(
                "firebase_order_update: could not load owner %s: %s",
                owner_shortname,
                exc,
            )
            return

        user_dict = user.model_dump()
        firebase_token = user_dict.get("firebase_token")
        if not firebase_token:
            logger.warning(
                "firebase_order_update: owner %s has no firebase_token, skipping push",
                owner_shortname,
            )
            return

        # Build localized title/body as simple translations with the same text in all languages.
        base_title = f"Order {state}"
        base_body = f"Your order {ticket_shortname} has been {state}."

        title = Translation(ar=base_title, en=base_title, ku=base_title)
        body = Translation(ar=base_body, en=base_body, ku=base_body)

        # Prepare NotificationData; image_urls and deep_link can be extended later if needed.
        notification_data = NotificationData(
            receiver=user_dict,
            title=title,
            body=body,
            image_urls=None,
            deep_link={},
            entry_id=ticket_shortname,
        )

        manager = NotificationManager()
        print(f"send notification to {owner_shortname} with data: {notification_data}")
        sent = await manager.send(platform="mobile", data=notification_data)
        logger.info(
            "firebase_order_update: sent=%s state=%s order=%s to owner=%s",
            sent,
            state,
            ticket_shortname,
            owner_shortname,
        )


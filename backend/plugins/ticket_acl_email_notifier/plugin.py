from models.core import PluginBase, Event, ActionType, Ticket, User
from models.enums import ResourceType
from utils.settings import settings
from data_adapters.adapter import data_adapter as db
from fastapi.logger import logger
from api.user.service import send_email


class Plugin(PluginBase):
    async def hook(self, data: Event):
        """
        Send email notifications to users when they are added to a ticket's ACL
        via update_acl request. Uses DMART's central SMTP (no separate plugin SMTP).
        """
        print(f"HEY I RAN .........................")
        if data.resource_type != ResourceType.ticket:
            return

        # update_acl request emits action_type=ActionType.update with history_diff
        if data.action_type != ActionType.update:
            return

        history_diff = data.attributes.get("history_diff", {})
        if "acl" not in history_diff:
            return

        if not isinstance(data.shortname, str):
            logger.warning(
                "data.shortname is None and str is required at ticket_acl_email_notifier"
            )
            return

        try:
            acl_diff = history_diff["acl"]
            old_acl = acl_diff.get("old", [])
            new_acl = acl_diff.get("new", [])

            if old_acl is None or old_acl == "null":
                old_acl = []
            if new_acl is None or new_acl == "null":
                new_acl = []

            if not isinstance(old_acl, list):
                old_acl = []
            if not isinstance(new_acl, list):
                new_acl = []

            old_user_shortnames = set()
            new_user_shortnames = set()

            for acl_entry in old_acl:
                if isinstance(acl_entry, dict) and "user_shortname" in acl_entry:
                    old_user_shortnames.add(acl_entry["user_shortname"])
                elif hasattr(acl_entry, "user_shortname"):
                    old_user_shortnames.add(acl_entry.user_shortname)

            for acl_entry in new_acl:
                if isinstance(acl_entry, dict) and "user_shortname" in acl_entry:
                    new_user_shortnames.add(acl_entry["user_shortname"])
                elif hasattr(acl_entry, "user_shortname"):
                    new_user_shortnames.add(acl_entry.user_shortname)

            newly_added_users = new_user_shortnames - old_user_shortnames

            if not newly_added_users:
                return

            ticket = await db.load(
                space_name=data.space_name,
                subpath=data.subpath,
                shortname=data.shortname,
                class_type=Ticket,
                user_shortname=data.user_shortname,
            )

            for user_shortname in newly_added_users:
                try:
                    user = await db.load(
                        space_name=settings.management_space,
                        subpath=settings.users_subpath,
                        shortname=user_shortname,
                        class_type=User,
                        user_shortname=data.user_shortname,
                    )

                    if not user.email:
                        logger.warning(
                            f"User {user_shortname} does not have an email address, skipping email notification"
                        )
                        continue

                    message = f"<p>Your action is needed for request with ID: {ticket.shortname}</p>"
                    subject = "Action Required for Request"
                    print(f"Sending email to {user.email} with message {message} and subject {subject}")
                    await send_email(
                        to_address=user.email,
                        message=message,
                        subject=subject,
                    )

                except Exception as e:
                    logger.error(
                        f"Error sending email notification to user {user_shortname} for ticket {ticket.shortname}: {e}"
                    )
        except Exception as e:
            logger.error(
                f"Error in ticket_acl_email_notifier plugin for ticket {data.shortname}: {e}"
            )

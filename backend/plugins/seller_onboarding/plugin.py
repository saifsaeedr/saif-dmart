from uuid import uuid4

from fastapi.logger import logger
from models.core import Content, Event, Folder, Payload, PluginBase, User
from models.enums import ContentType, ResourceType
from data_adapters.adapter import data_adapter as db
from utils.settings import settings

SELLER_ROLE = "zm_seller"
SPACE_NAME = "zainmart"


SELLERS_SUBPATH = "sellers"

SELLER_SUBPATHS = [
    "available_products",
    "orders",
    "warranties",
    "service",
    "discounts",
    "coupons",
    "shipping",
]

SHIPPING_CONFIG_PAYLOAD = {
    "items": [
        {
            "settings": [
                {
                    "key": "bd11ab93-f889-4b61-9720-60cd51dba276",
                    "max": 5,
                    "min": 1,
                    "cost": 10000,
                    "note": {
                        "ar": "اعتيادي",
                        "en": "stanrded",
                    },
                    "is_active": True,
                    "minimum_retail": 5000,
                }
            ]
        }
    ]
}


class Plugin(PluginBase):
    async def hook(self, data: Event) -> None:
        if not isinstance(data.shortname, str):
            logger.error("seller_onboarding: data.shortname is required")
            return

        if data.resource_type != ResourceType.user:
            return

        if data.action_type.value != "create":
            return

        user_shortname = data.shortname
        subpath = data.subpath.lstrip("/") if data.subpath.startswith("/") else data.subpath
        user = await db.load_or_none(
            space_name=data.space_name,
            subpath=subpath,
            shortname=user_shortname,
            class_type=User,
            user_shortname=data.user_shortname,
        )

        if user is None:
            logger.warning(f"seller_onboarding: could not load user {user_shortname}")
            return

        if SELLER_ROLE not in (user.roles or []):
            return

        displayname = user.displayname
        owner_shortname = user_shortname

        for subpath in SELLER_SUBPATHS:
            try:
                folder_subpath = subpath
                existing_folder = await db.load_or_none(
                    space_name=SPACE_NAME,
                    subpath=folder_subpath,
                    shortname=user_shortname,
                    class_type=Folder,
                    user_shortname=owner_shortname,
                )

                if existing_folder is None:
                    await db.internal_save_model(
                        space_name=SPACE_NAME,
                        subpath=folder_subpath,
                        meta=Folder(
                            shortname=user_shortname,
                            displayname=displayname,
                            is_active=True,
                            owner_shortname=owner_shortname,
                        ),
                    )

                if subpath == "shipping":
                    shipping_folder_subpath = f"{subpath}/{user_shortname}"
                    existing_config = await db.load_or_none(
                        space_name=SPACE_NAME,
                        subpath=shipping_folder_subpath,
                        shortname="config",
                        class_type=Content,
                        user_shortname=owner_shortname,
                    )

                    if existing_config is None:
                        config_content = Content(
                            uuid=uuid4(),
                            shortname="config",
                            is_active=True,
                            owner_shortname=owner_shortname,
                            payload=Payload(
                                content_type=ContentType.json,
                                schema_shortname=None,
                                body=SHIPPING_CONFIG_PAYLOAD,
                            ),
                        )
                        await db.save(
                            space_name=SPACE_NAME,
                            subpath=shipping_folder_subpath,
                            meta=config_content,
                        )

            except Exception as e:
                logger.error(
                    f"seller_onboarding: failed to create folder {subpath}/{user_shortname}: {e}",
                    exc_info=True,
                )

        try:
            existing_seller_entry = await db.load_or_none(
                space_name=SPACE_NAME,
                subpath=SELLERS_SUBPATH,
                shortname=user_shortname,
                class_type=Content,
                user_shortname=owner_shortname,
            )

            if existing_seller_entry is None:
                seller_content = Content(
                    uuid=uuid4(),
                    shortname=user_shortname,
                    displayname=displayname,
                    is_active=True,
                    owner_shortname=owner_shortname,
                    payload=Payload(
                        content_type=ContentType.json,
                        schema_shortname=None,
                        body={
                            "phone": user.msisdn or ""
                        },
                    ),
                )
                await db.save(
                    space_name=SPACE_NAME,
                    subpath=SELLERS_SUBPATH,
                    meta=seller_content,
                )
        except Exception as e:
            logger.error(
                f"seller_onboarding: failed to create sellers entry {user_shortname}: {e}",
                exc_info=True,
            )

        try:
            await db.internal_sys_update_model(
                space_name=settings.management_space,
                subpath=settings.users_subpath,
                meta=user,
                updates={
                    "is_msisdn_verified": True,
                    "is_email_verified": True,
                    "is_active": True,
                },
            )
        except Exception as e:
            logger.error(
                f"seller_onboarding: failed to update user {user_shortname}: {e}",
                exc_info=True,
            )

from __future__ import annotations

import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MetaWhatsAppConfig:
    access_token: str
    graph_api_version: str
    webhook_verify_token: str
    webhook_app_secret: str
    sender_hash_secret: str

    @classmethod
    def from_environment(cls) -> MetaWhatsAppConfig | None:
        names = (
            "META_WHATSAPP_ACCESS_TOKEN",
            "META_GRAPH_API_VERSION",
            "META_WHATSAPP_VERIFY_TOKEN",
            "META_WHATSAPP_APP_SECRET",
            "WHATSAPP_SENDER_HASH_SECRET",
        )
        values = {name: os.environ.get(name, "").strip() for name in names}

        if not any(values.values()):
            return None

        missing = [name for name, value in values.items() if not value]
        if missing:
            raise RuntimeError(
                "Incomplete Meta WhatsApp configuration: "
                + ", ".join(missing)
            )

        if not re.fullmatch(r"v\d+\.\d+", values["META_GRAPH_API_VERSION"]):
            raise ValueError("META_GRAPH_API_VERSION must look like vXX.X.")

        return cls(
            access_token=values["META_WHATSAPP_ACCESS_TOKEN"],
            graph_api_version=values["META_GRAPH_API_VERSION"],
            webhook_verify_token=values["META_WHATSAPP_VERIFY_TOKEN"],
            webhook_app_secret=values["META_WHATSAPP_APP_SECRET"],
            sender_hash_secret=values["WHATSAPP_SENDER_HASH_SECRET"],
        )

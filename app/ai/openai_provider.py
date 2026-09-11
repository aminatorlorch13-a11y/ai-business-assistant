from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ai.errors import AIProviderError
from app.ai.openai_config import OpenAIConfig
from app.ai.raw_provider import RawAIProvider
from app.assistant.message import AssistantMessage


class OpenAIHTTPProvider(RawAIProvider):
    """
    Production OpenAI Responses API adapter.

    The provider returns structured data only.
    AI output remains untrusted and must pass through AIResponseParser
    before it becomes an application interpretation.
    """

    RESPONSE_SCHEMA = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "intent_type": {
                "type": "string",
                "enum": [
                    "general_question",
                    "customer_request",
                    "business_task",
                ],
            },
            "instruction": {
                "type": "string",
            },
            "action_type": {
                "type": "string",
                "enum": [
                    "none",
                    "create",
                    "update",
                    "delete",
                ],
            },
            "target": {
                "type": "string",
            },
            "action_instruction": {
                "type": "string",
            },
            "business_id": {
                "type": "string",
            },
        },
        "required": [
            "intent_type",
            "instruction",
            "action_type",
            "target",
            "action_instruction",
            "business_id",
        ],
    }

    SYSTEM_INSTRUCTIONS = """
You are the intelligence layer of a business assistant.

Understand the user's actual request from natural language.

You are not a keyword classifier.

A user may:
- ask a normal question;
- have a conversation;
- ask for information;
- ask the assistant to perform business work;
- refer to something mentioned earlier;
- speak naturally with incomplete sentences;
- use different wording for the same task.

Never invent facts, actions, results, messages, emails, documents,
appointments, customers, or external-system activity.

At this stage you are producing a structured interpretation for the
application. You are NOT directly executing anything.

Rules:

1. intent_type:
   general_question = ordinary conversation/questions.
   customer_request = customer-related request.
   business_task = a request to perform business work.

2. action_type:
   none = no external/business-changing action is being requested.
   create = create something.
   update = modify something.
   delete = remove something.

3. If required information is missing, do not invent it.
   Preserve what the user actually said in instruction and action_instruction.

4. target must identify the actual subject of the requested operation.
   Do not manufacture identifiers.

5. business_id must contain the business identity supplied by the
   application context.

6. Never claim that an action has already happened.
   This response only describes what the application should understand.

7. Preserve natural conversational meaning. Do not require exact keywords.

Return only the requested structured object.
""".strip()

    def __init__(
        self,
        config: OpenAIConfig,
    ) -> None:
        if not isinstance(config, OpenAIConfig):
            raise TypeError(
                "config must be an OpenAIConfig."
            )

        self._config = config

    def generate(
        self,
        message: AssistantMessage,
    ) -> Mapping[str, object]:
        if not isinstance(message, AssistantMessage):
            raise TypeError(
                "message must be an AssistantMessage."
            )

        payload = {
            "model": self._config.model,
            "instructions": self.SYSTEM_INSTRUCTIONS,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Application business_id: "
                                f"{message.business_id}\n\n"
                                "Owner message:\n"
                                f"{message.content}"
                            ),
                        }
                    ],
                }
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "assistant_interpretation",
                    "strict": True,
                    "schema": self.RESPONSE_SCHEMA,
                }
            },
        }

        request = Request(
            url=f"{self._config.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": (
                    f"Bearer {self._config.api_key}"
                ),
                "Content-Type": "application/json",
            },
        )

        try:
            with urlopen(
                request,
                timeout=self._config.timeout_seconds,
            ) as response:
                raw_body = response.read()

        except HTTPError as exc:
            raise AIProviderError(
                f"OpenAI API request failed with HTTP {exc.code}."
            ) from exc

        except URLError as exc:
            raise AIProviderError(
                "Unable to connect to the OpenAI API."
            ) from exc

        except TimeoutError as exc:
            raise AIProviderError(
                "OpenAI API request timed out."
            ) from exc

        except OSError as exc:
            raise AIProviderError(
                "OpenAI API network request failed."
            ) from exc

        try:
            response_data = json.loads(
                raw_body.decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIProviderError(
                "OpenAI returned invalid JSON."
            ) from exc

        return self._extract_structured_output(
            response_data
        )

    @staticmethod
    def _extract_structured_output(
        response_data: object,
    ) -> Mapping[str, object]:
        if not isinstance(response_data, Mapping):
            raise AIProviderError(
                "OpenAI response must be a mapping."
            )

        output = response_data.get("output")

        if not isinstance(output, list):
            raise AIProviderError(
                "OpenAI response contains no valid output list."
            )

        for item in output:
            if not isinstance(item, Mapping):
                continue

            if item.get("type") != "message":
                continue

            content = item.get("content")

            if not isinstance(content, list):
                continue

            for content_item in content:
                if not isinstance(
                    content_item,
                    Mapping,
                ):
                    continue

                if content_item.get("type") != "output_text":
                    continue

                text = content_item.get("text")

                if not isinstance(text, str) or not text.strip():
                    continue

                try:
                    structured = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise AIProviderError(
                        "OpenAI returned invalid structured output."
                    ) from exc

                if not isinstance(structured, Mapping):
                    raise AIProviderError(
                        "OpenAI structured output must be a mapping."
                    )

                return structured

        raise AIProviderError(
            "OpenAI response did not contain structured output."
        )

from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.ai.errors import AIProviderError
from app.ai.groq_config import GroqConfig
from app.ai.raw_provider import RawAIProvider
from app.assistant.message import AssistantMessage


class GroqHTTPProvider(RawAIProvider):
    """
    Production Groq chat-completions adapter.

    Groq's API is OpenAI-compatible in shape but does not support
    strict json_schema mode. The system prompt explicitly names the
    required fields and the closed-world target/action rules enforced
    downstream by AIInterpretationValidator. AIResponseParser and
    AIInterpretationValidator remain the real security boundaries
    that validate the output regardless of what the model returns.
    """

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

1. intent_type must be exactly one of:
   "general_question", "customer_request", "business_task".

2. action_type must be exactly one of:
   "none", "create", "update", "delete".

3. If required information is missing, do not invent it.
   Preserve what the user actually said in instruction.

4. target must be exactly one of these fixed values, depending on
   action_type:
   - If action_type is "none": target must be "assistant" for a
     greeting, general conversation, or question with no specific
     business subject, OR "appointment" if the user is asking about
     an appointment without changing it.
   - If action_type is "create", "update", or "delete": target must
     be "appointment". No other target values exist yet.
   Never invent a target value outside this fixed list.

5. action_instruction has two different meanings depending on target:
   - If target is "assistant": action_instruction must contain your
     actual natural-language reply to the user, written directly to
     them, warm and conversational. This is the text that will be
     spoken back to the user verbatim.
   - If target is "appointment": action_instruction must describe
     the requested appointment action in the user's own words (for
     "none", briefly state what appointment information they asked
     about).

6. business_id must contain the business identity supplied by the
   application context.

7. Never claim that an action has already happened.
   This response only describes what the application should
   understand.

8. Preserve natural conversational meaning. Do not require exact
   keywords.

9. Every field must be a non-empty string. Never return an empty
   string for any field.

You must respond with ONLY a single JSON object, and nothing else,
containing exactly these fields:

{
  "intent_type": "...",
  "instruction": "...",
  "action_type": "...",
  "target": "...",
  "action_instruction": "...",
  "business_id": "..."
}

Do not include any explanation, markdown formatting, or text outside
the JSON object.
""".strip()

    def __init__(
        self,
        config: GroqConfig,
    ) -> None:
        if not isinstance(config, GroqConfig):
            raise TypeError(
                "config must be a GroqConfig."
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
            "temperature": 0,
            "response_format": {
                "type": "json_object",
            },
            "messages": [
                {
                    "role": "system",
                    "content": self.SYSTEM_INSTRUCTIONS,
                },
                {
                    "role": "user",
                    "content": (
                        "Application business_id: "
                        f"{message.business_id}\n\n"
                        "Owner message:\n"
                        f"{message.content}"
                    ),
                },
            ],
        }

        request = Request(
            url=f"{self._config.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 10) "
                    "AI-Business-Assistant/1.0"
                ),
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
                f"Groq API request failed with HTTP {exc.code}."
            ) from exc

        except URLError as exc:
            raise AIProviderError(
                "Unable to connect to the Groq API."
            ) from exc

        except TimeoutError as exc:
            raise AIProviderError(
                "Groq API request timed out."
            ) from exc

        except OSError as exc:
            raise AIProviderError(
                "Groq API network request failed."
            ) from exc

        try:
            response_data = json.loads(
                raw_body.decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIProviderError(
                "Groq returned invalid JSON."
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
                "Groq response must be a mapping."
            )

        choices = response_data.get("choices")

        if not isinstance(choices, list) or not choices:
            raise AIProviderError(
                "Groq response contains no choices."
            )

        first_choice = choices[0]

        if not isinstance(first_choice, Mapping):
            raise AIProviderError(
                "Groq response choice must be a mapping."
            )

        message_obj = first_choice.get("message")

        if not isinstance(message_obj, Mapping):
            raise AIProviderError(
                "Groq response choice has no message."
            )

        content = message_obj.get("content")

        if not isinstance(content, str) or not content.strip():
            raise AIProviderError(
                "Groq response message has no content."
            )

        try:
            structured = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIProviderError(
                "Groq returned invalid structured output."
            ) from exc

        if not isinstance(structured, Mapping):
            raise AIProviderError(
                "Groq structured output must be a mapping."
            )

        return structured

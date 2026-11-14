from pathlib import Path

changes = {
    "app/ai/context.py": [
        (
            "        automation_context: AutomationContext | None = None,\n    ) -> None:",
            "        automation_context: AutomationContext | None = None,\n"
            "        query: str | None = None,\n    ) -> None:",
        ),
        (
            "        business_id = memory_context.business_id",
            '        if query is not None and not isinstance(query, str):\n'
            '            raise TypeError("query must be a string or None.")\n\n'
            "        business_id = memory_context.business_id",
        ),
        (
            "        self._automation_context = automation_context\n"
            "    @property\n"
            "    def memory_context",
            "        self._automation_context = automation_context\n"
            "        self._query = query\n\n"
            "    @property\n"
            "    def query(self) -> str | None:\n"
            '        """Return the current request used for context retrieval."""\n'
            "        return self._query\n\n"
            "    @property\n"
            "    def memory_context",
        ),
    ],
    "app/assistant/processor.py": [
        (
            "            automation_context=automation_context,\n        )",
            "            automation_context=automation_context,\n"
            "            query=message.content,\n        )",
        ),
    ],
    "app/assistant/structured_processor.py": [
        (
            "        memory_context = self._memory_context_builder.build(\n"
            "            message.business_id\n"
            "        )\n"
            "        context = AIContext(\n"
            "            memory_context,\n"
            "            conversation_history=conversation_history,\n"
            "            automation_context=automation_context,\n"
            "        )",
            "        memory_context = self._memory_context_builder.build(\n"
            "            message.business_id, query=message.content\n"
            "        )\n"
            "        context = AIContext(\n"
            "            memory_context,\n"
            "            conversation_history=conversation_history,\n"
            "            automation_context=automation_context,\n"
            "            query=message.content,\n"
            "        )",
        ),
    ],
}

loaded = {}

for filename, replacements in changes.items():
    path = Path(filename)
    source = path.read_text()
    for old, new in replacements:
        count = source.count(old)
        if count != 1:
            raise SystemExit(
                f"STOP: expected one match in {filename}, found {count}.\n"
                f"Fragment:\n{old}"
            )
        source = source.replace(old, new, 1)
    loaded[path] = source

path = Path("app/ai/privacy_context_builder.py")
source = path.read_text()

if "import re\n" not in source:
    marker = "from __future__ import annotations\n"
    if source.count(marker) != 1:
        raise SystemExit("STOP: cannot safely add the re import.")
    source = source.replace(marker, marker + "\nimport re\n", 1)

start = "    def _build_conversation(self, context: AIContext) -> str:\n"
end = "    def _build_automation(self, context: AIContext) -> str:\n"

if source.count(start) != 1 or source.count(end) != 1:
    raise SystemExit("STOP: conversation-builder boundaries are not unique.")

left = source.index(start)
right = source.index(end)
if right <= left:
    raise SystemExit("STOP: invalid method boundaries.")

method = '''    def _build_conversation(self, context: AIContext) -> str:
        history = context.conversation_history
        if history.is_empty:
            return "Conversation history: (none)"

        lines = [
            f"[{turn.role.value}] {turn.content}"
            for turn in history.turns
        ]
        complete_text = self._HISTORY_HEADER + "\\\\n" + "\\\\n".join(lines)
        maximum = self.MAX_CONVERSATION_CHARS
        if len(complete_text) <= maximum:
            return complete_text

        fixed = self._HISTORY_HEADER + "\\\\n" + self._OMISSION_MARKER + "\\\\n"
        remaining = maximum - len(fixed)
        if remaining <= 0:
            return self._limit(self._HISTORY_HEADER, maximum)

        query_terms = {
            term
            for term in re.findall(r"[a-z0-9]{3,}", (context.query or "").lower())
            if term not in {
                "the", "and", "for", "what", "when", "where", "which",
                "with", "from", "that", "this", "was", "were", "are",
                "you", "your", "please", "could", "would", "should",
                "have", "has", "had", "about", "into", "tell", "remind",
            }
        }
        if not query_terms:
            return self._select_newest(lines, fixed, remaining)

        selected: dict[int, str] = {}
        used = 0
        recent_budget = max(1, int(remaining * 0.60))

        # Keep the newest turn even when it exceeds the soft recent budget.
        for index in range(len(lines) - 1, -1, -1):
            line = lines[index]
            cost = len(line) + (1 if selected else 0)

            if not selected and len(line) > remaining:
                role_end = line.find("] ") + 2
                prefix = line[:role_end] + self._OVERSIZED_TURN_MARKER
                available = remaining - len(prefix)
                if available > 0:
                    return fixed + prefix + line[-available:]
                return self._limit(fixed, maximum)

            if used + cost > remaining or (
                selected and used + cost > recent_budget
            ):
                break
            selected[index] = line
            used += cost

        def relevance(index: int) -> tuple[int, int]:
            words = set(re.findall(r"[a-z0-9]{3,}", lines[index].lower()))
            return len(query_terms & words), index

        candidates = sorted(
            (
                index for index in range(len(lines))
                if index not in selected and relevance(index)[0] > 0
            ),
            key=relevance,
            reverse=True,
        )

        for index in candidates:
            line = lines[index]
            cost = len(line) + (1 if selected else 0)
            if used + cost <= remaining:
                selected[index] = line
                used += cost

        rendered = "\\\\n".join(selected[index] for index in sorted(selected))
        result = fixed + rendered
        if len(result) > maximum:
            raise AssertionError("Conversation context exceeded its character budget.")
        return result

    def _select_newest(
        self, lines: list[str], fixed: str, remaining: int
    ) -> str:
        selected: list[str] = []
        used = 0
        for line in reversed(lines):
            cost = len(line) + (1 if selected else 0)
            if used + cost <= remaining:
                selected.append(line)
                used += cost
                continue

            if not selected:
                role_end = line.find("] ") + 2
                prefix = line[:role_end] + self._OVERSIZED_TURN_MARKER
                available = remaining - len(prefix)
                if available > 0:
                    selected.append(prefix + line[-available:])
            break

        selected.reverse()
        return fixed + "\\\\n".join(selected)

'''

source = source[:left] + method + source[right:]
loaded[path] = source

# All checks have passed. Only now write the files.
for path, source in loaded.items():
    path.write_text(source)
    print(f"Updated {path}")

print("Patch applied. No conversation records or Git history were changed.")

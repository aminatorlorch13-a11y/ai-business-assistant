import ast
from pathlib import Path

targets = {
    "tests/test_assistant_orchestrator.py": [
        "test_orchestrator_executes_interpreted_action",
        "test_orchestrator_does_not_return_success_when_execution_fails",
        "test_orchestrator_forwards_authenticated_tenant_to_executor",
    ],
    "tests/test_structured_assistant_orchestrator.py": [
        "test_successful_non_confirmed_capability_executes_through_executor",
        "test_execution_failure_is_returned_as_failure_not_success",
        "test_authenticated_tenant_is_forwarded_exactly_to_executor",
    ],
}

def offset(source, line, column):
    lines = source.splitlines(keepends=True)
    return sum(len(x) for x in lines[:line - 1]) + column

updates = {}

for filename, names in targets.items():
    path = Path(filename)
    source = path.read_text()
    tree = ast.parse(source)
    edits = []

    for name in names:
        functions = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        ]
        assert len(functions) == 1, f"{filename}: expected one {name}"

        fn = functions[0]
        calls = [
            node for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "handle"
            and not any(k.arg == "confirmation_id" for k in node.keywords)
            and node.args
        ]
        assert len(calls) == 1, f"{name}: expected one initial handle call"
        call = calls[0]

        statements = [
            node for node in ast.walk(fn)
            if isinstance(node, (ast.Assign, ast.Expr))
            and hasattr(node, "end_lineno")
            and node.lineno <= call.lineno <= node.end_lineno
            and node.col_offset <= call.col_offset
            and node.end_lineno >= call.end_lineno
        ]
        statement = min(
            statements,
            key=lambda node: (
                node.end_lineno - node.lineno,
                node.col_offset,
            ),
        )
        assert isinstance(statement, (ast.Assign, ast.Expr))
        assigned_result = (
            isinstance(statement, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "result"
                    for t in statement.targets)
        )

        message = ast.get_source_segment(source, call.args[0])
        assert message
        has_tenant_variable = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "tenant"
                    for t in node.targets)
            and node.lineno < statement.lineno
            for node in ast.walk(fn)
        )

        indent = " " * statement.col_offset
        block = []
        if not has_tenant_variable:
            block.append("tenant = make_tenant()")

        block.extend([
            "first = orchestrator.handle(",
            "    " + message.replace("\n", "\n    ") + ",",
            "    tenant=tenant,",
            ")",
            'assert "Confirmation ID: " in first.message',
            'confirmation_id = first.message.split("Confirmation ID: ", 1)[1]',
        ])

        if assigned_result:
            block.extend([
                "result = orchestrator.handle(",
                "    " + message.replace("\n", "\n    ") + ",",
                "    tenant=tenant,",
                "    confirmation_id=confirmation_id,",
                ")",
            ])
        else:
            block.extend([
                "orchestrator.handle(",
                "    " + message.replace("\n", "\n    ") + ",",
                "    tenant=tenant,",
                "    confirmation_id=confirmation_id,",
                ")",
            ])

        replacement = ("\n" + indent).join(block)
        edits.append((
            offset(source, statement.lineno, statement.col_offset),
            offset(source, statement.end_lineno, statement.end_col_offset),
            replacement,
        ))

    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]

    ast.parse(source)
    updates[filename] = source

for filename, source in updates.items():
    Path(filename).write_text(source)
    print(f"Updated confirmation flow tests: {filename}")

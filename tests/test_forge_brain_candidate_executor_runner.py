import json
from types import SimpleNamespace
from unittest.mock import Mock

from app.assistant.structured_processor import StructuredAssistantProcessor
from app.forge.brain_candidate_executor import ForgeBrainCandidateExecutor
from app.forge.task_spec import ForgeTaskSpec
from app.forge.worker import ForgeExecutionContext


def make_context():
    context = object.__new__(ForgeExecutionContext)
    context.check_cancellation = lambda: None
    context.check_lease = lambda: None
    context.report_progress = lambda *_args: None
    return context


def make_spec(language="python"):
    return ForgeTaskSpec(
        business_id="business-test",
        project_id="project-test",
        job_id="job-test",
        instructions="Create a small source file.",
        scope=("main.py",),
        acceptance_criteria=("The source file is valid.",),
        language=language,
    )


def make_processor(files):
    processor = Mock(spec=StructuredAssistantProcessor)
    processor.process.return_value = SimpleNamespace(
        response=json.dumps({"files": files})
    )
    return processor


def make_runner(exit_code=0, timed_out=False):
    runner = Mock()
    runner.open_session.return_value = "a" * 32
    runner.execute.return_value = {
        "exit_code": exit_code,
        "output": "",
        "timed_out": timed_out,
    }
    return runner


def test_brain_candidate_is_compiled_in_runner_and_session_is_closed():
    runner = make_runner()
    executor = ForgeBrainCandidateExecutor(
        make_processor({"main.py": "print('hello')"}),
        runner_client=runner,
    )

    result = executor(make_spec(), make_context())

    runner.open_session.assert_called_once()
    runner.execute.assert_called_once()
    command = runner.execute.call_args.args[1]
    assert command == "python -m py_compile ./main.py"
    runner.close_session.assert_called_once_with("a" * 32)
    assert result.candidate["runner_verification"]["status"] == "pass"
    assert result.candidate["execution_policy"]["generated_code_executed"] is False
    assert result.candidate["execution_policy"]["live_repository_modified"] is False
    assert result.candidate["execution_policy"]["isolated_runner_commands_invoked"] is True


def test_compile_failure_is_recorded_without_claiming_success():
    runner = make_runner(exit_code=1)
    executor = ForgeBrainCandidateExecutor(
        make_processor({"main.py": "def valid_function():\n    return 1\n"}),
        runner_client=runner,
    )

    result = executor(make_spec(), make_context())

    assert result.candidate["runner_verification"]["status"] == "fail"
    assert result.candidate["toolchain_plan"]["execution_status"] == "isolated_compile_failed"
    runner.close_session.assert_called_once_with("a" * 32)


def test_missing_runner_is_reported_without_execution():
    executor = ForgeBrainCandidateExecutor(
        make_processor({"main.py": "print('hello')"})
    )

    result = executor(make_spec(), make_context())

    assert result.candidate["runner_verification"]["status"] == "not_configured"
    assert result.candidate["runner_verification"]["executed"] is False


def test_runner_session_is_closed_when_execution_raises():
    runner = make_runner()
    runner.execute.side_effect = RuntimeError("runner unavailable")
    executor = ForgeBrainCandidateExecutor(
        make_processor({"main.py": "print('hello')"}),
        runner_client=runner,
    )

    try:
        executor(make_spec(), make_context())
    except RuntimeError as exc:
        assert "runner unavailable" in str(exc)
    else:
        raise AssertionError("Expected runner execution failure.")

    runner.close_session.assert_called_once_with("a" * 32)


def test_filename_starting_with_dash_is_passed_as_relative_path():
    runner = make_runner()
    executor = ForgeBrainCandidateExecutor(
        make_processor({"-module.py": "print('safe')"}),
        runner_client=runner,
    )

    executor(make_spec(), make_context())

    command = runner.execute.call_args.args[1]
    assert command == "python -m py_compile ./-module.py"

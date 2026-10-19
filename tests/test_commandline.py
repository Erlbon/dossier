import sys
import time

import pytest

from dossier.core.commandline import Placeholders, expand, run_command
from dossier.core.terminals import Profile, UnsafeArgument, custom_profile

CMD = Profile("cmd", "Command Prompt", "cmd", "cmd.exe")
PS = Profile("powershell", "Windows PowerShell", "powershell", "powershell.exe")
SH = Profile("sh", "sh", "posix", "sh")
PH = Placeholders(current_name="my file.txt", current_path="C:\\w\\my file.txt",
                  marked=("C:\\w\\a.txt", "C:\\w\\b c.txt"), folder="C:\\w", other="D:\\o")


# placeholders --------------------------------------------------------------------------------------------
def test_each_placeholder_is_quoted_for_the_interpreter():
    assert expand("copy %f x", PH, CMD) == 'copy "my file.txt" x'
    assert expand("type %p", PH, PS) == "type 'C:\\w\\my file.txt'"
    assert expand("cd %d && cd %o", PH, SH) == "cd 'C:\\w' && cd 'D:\\o'"


def test_marked_items_become_several_words_and_fall_back_to_the_current_item():
    assert expand("zip %s", PH, PS) == "zip 'C:\\w\\a.txt' 'C:\\w\\b c.txt'"
    single = Placeholders(current_path="C:\\w\\x.txt")
    assert expand("zip %s", single, PS) == "zip 'C:\\w\\x.txt'"


def test_percent_percent_is_a_percent_and_unknown_codes_stay_as_typed():
    assert expand("echo 100%% %z", PH, SH) == "echo 100% %z"
    assert expand("echo %", PH, SH) == "echo %"


def test_a_placeholder_without_a_value_is_an_error():
    with pytest.raises(ValueError, match="%f"):
        expand("open %f", Placeholders(), PS)
    with pytest.raises(ValueError):
        expand("cd %o", Placeholders(current_name="x", current_path="x"), PS)


def test_hostile_names_are_refused_or_neutralised_not_executed():
    evil = Placeholders(current_name="a&calc.txt", current_path="C:\\w\\a&calc.txt")
    assert expand("type %f", evil, CMD) == 'type "a&calc.txt"'
    bad = Placeholders(current_name='x" & calc & ".txt', current_path="x")
    with pytest.raises(UnsafeArgument):
        expand("type %f", bad, CMD)
    quote_attack = Placeholders(current_name="x'; calc; '", current_path="x")
    assert expand("echo %f", quote_attack, PS) == "echo 'x''; calc; '''"


# running -------------------------------------------------------------------------------------------------------
def py(code: str) -> str:
    return f'"{sys.executable}" -c "{code}"'


RAW = custom_profile("{command}")


def test_a_command_runs_and_its_output_is_captured(tmp_path):
    result = run_command(RAW, py("print(42)"), str(tmp_path))
    assert result.finished and result.exit_code == 0 and result.output.strip() == "42"


def test_it_runs_in_the_given_folder(tmp_path):
    result = run_command(RAW, py("import os; print(os.getcwd())"), str(tmp_path))
    assert result.output.strip().lower().replace("\\", "/").endswith(tmp_path.name.lower())


def test_stderr_is_merged_and_the_exit_code_is_reported(tmp_path):
    result = run_command(RAW, py("import sys; sys.stderr.write('oops'); sys.exit(3)"), str(tmp_path))
    assert result.exit_code == 3 and "oops" in result.output


def test_a_command_still_running_is_left_running_and_reported(tmp_path):
    started = time.time()
    result = run_command(RAW, py("import time; time.sleep(2); print('late')"), str(tmp_path), wait=0.3)
    assert not result.finished and result.exit_code is None and result.pid > 0
    assert time.time() - started < 1.5


def test_a_huge_output_is_cut_and_the_process_does_not_block(tmp_path):
    result = run_command(RAW, py("print('x' * 3000000)"), str(tmp_path), wait=20, max_output=100_000)
    assert result.finished and result.truncated and len(result.output) <= 100_000


def test_an_unknown_program_is_an_error_not_a_hang(tmp_path):
    result = run_command(RAW, "definitely_not_a_program_xyz", str(tmp_path))
    assert result.finished and result.exit_code not in (0, None) and result.output


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="PowerShell test needs Windows PowerShell")
def test_powershell_runs_through_the_encoded_command(tmp_path):
    from dossier.core.terminals import WINDOWS_PROFILES
    ps = next(p for p in WINDOWS_PROFILES if p.id == "powershell")
    result = run_command(ps, "Write-Output ('a' + 'b')", str(tmp_path), wait=30)
    assert result.finished and result.output.strip() == "ab"

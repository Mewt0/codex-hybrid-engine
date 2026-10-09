from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the project root and the tests directory importable regardless of the
# pytest rootdir (tests import each other, e.g. `from test_engine import ...`).
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
for entry in (str(PROJECT_ROOT), str(TESTS_DIR)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


def make_executable_stub(directory: Path, name: str, python_code: str) -> Path:
    """Create a portable executable stub that runs `python_code`.

    POSIX gets a `#!/bin/sh` wrapper, Windows gets a `.cmd` wrapper. Both call
    the same Python snippet, so provider tests exercise identical behaviour on
    both platforms instead of failing with WinError 193.
    """
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    if os.name == "nt":
        target = directory / f"{name}.cmd"
        target.write_text(
            "@echo off\r\n\"%s\" -c \"%s\"\r\n" % (sys.executable, python_code.replace('"', '\\"')),
            encoding="utf-8",
            newline="\r\n",
        )
    else:
        target.write_text(
            "#!/bin/sh\nexec %s -c %s\n" % (sys.executable, _shell_quote(python_code)),
            encoding="utf-8",
        )
        target.chmod(0o755)
    return target


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"

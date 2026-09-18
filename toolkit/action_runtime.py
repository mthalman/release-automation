import subprocess
import sys
import tempfile
import venv
from pathlib import Path


def main() -> None:
    if sys.argv[1:] not in (["prepare"], ["finalize"]):
        raise ValueError("Expected prepare or finalize.")
    toolkit = Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix="release-automation-python-") as directory:
        environment = Path(directory)
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([
            str(python), "-I", "-m", "pip", "install", "--disable-pip-version-check",
            "-r", str(toolkit / "requirements.txt"),
        ], check=True)
        subprocess.run([
            str(python), "-I", str(toolkit / "publish.py"), sys.argv[1],
        ], check=True)


if __name__ == "__main__":
    main()

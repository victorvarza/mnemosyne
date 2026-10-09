import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


def test_pull_models_stops_after_the_first_failed_pull(tmp_path):
    log_path = tmp_path / "pulls.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ollama = bin_dir / "ollama"
    ollama.write_text(
        "#!/bin/sh\n"
        "echo \"$@\" >> \"$PULL_LOG\"\n"
        '[ "$2" = "first-model" ] && exit 23\n'
        "exit 0\n"
    )
    ollama.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "PULL_LOG": str(log_path),
    }

    result = subprocess.run(
        [
            "make",
            "-C",
            str(PROJECT_ROOT),
            "pull-models",
            "MNEMO_LLM_MODEL=first-model",
            "MNEMO_EMBED_MODEL=second-model",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert log_path.read_text().splitlines() == ["pull first-model"]

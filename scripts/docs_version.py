"""Keep the documentation header tied to the version being built."""

import tomllib
from pathlib import Path
from typing import Any


def on_config(config: Any) -> Any:
    project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
    with project_file.open("rb") as stream:
        project = tomllib.load(stream)["project"]
    config["repo_name"] = f"v{project['version']}"
    return config

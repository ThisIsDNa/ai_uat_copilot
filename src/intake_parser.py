########################################################
#
#  What this does:
#   - Reads your Scenario File
#   - Returns a Dictionary
#   - Provides a Clean Error if file path is wrong
#
########################################################

import json
from pathlib import Path

from src.scenario_builder_core import normalize_loaded_scenario_dict
from src.scenario_media import normalize_scenario_image_paths


def load_scenario(file_path: str) -> dict:
    """
    Load a scenario JSON file and return it as a Python dictionary.

    Image paths in ``workflow_process_screenshots`` and ``test_cases[].expected_step_screenshots``
    that are not already valid project-root-relative paths are resolved against the JSON file's
    directory (e.g. ``./shot.png`` next to the scenario file). Missing files do not raise;
    see optional ``ingestion_meta`` on the returned dict.
    """
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Scenario file not found: {file_path}")

    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    if isinstance(data, dict):
        normalize_loaded_scenario_dict(data)
        normalize_scenario_image_paths(data, path.parent.resolve())
    return data
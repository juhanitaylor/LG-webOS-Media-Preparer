"""Per-user GUI preferences. Source media and job options are kept separate."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import PROFILES


@dataclass(frozen=True)
class Preferences:
    input_path: str = ""
    output_path: str = ""
    profile: str = "bx"


def preferences_path() -> Path:
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(root) / "LG webOS Media Preparer" / "settings.json"


def load_preferences() -> Preferences:
    try:
        data = json.loads(preferences_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Preferences()
    if not isinstance(data, dict):
        return Preferences()
    paths = [data.get(key, "") for key in ("input_path", "output_path")]
    profile = data.get("profile")
    return Preferences(*(path if isinstance(path, str) else "" for path in paths),
                       profile if isinstance(profile, str) and profile in PROFILES else "bx")


def save_preferences(preferences: Preferences) -> None:
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".settings-", delete=False) as pending:
        temp = Path(pending.name)
        try:
            pending.write((json.dumps(asdict(preferences), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            pending.close()
            temp.replace(path)
        finally:
            pending.close()
            temp.unlink(missing_ok=True)

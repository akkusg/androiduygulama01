from __future__ import annotations

import os
import shutil
from pathlib import Path


def executable_available(command: str | None) -> bool:
    if not command:
        return False
    path = Path(command)
    if path.is_absolute():
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(command) is not None

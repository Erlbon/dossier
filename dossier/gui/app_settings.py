"""The settings file of the program: a plain ``dossier.ini`` in the user's config folder (never the registry). The window and the stand-alone
picture viewer open the same one, so a look chosen in one is seen by the other. With REDACTOR_CONFIG_DIR set (the release gate's scratch
profile), the file is there instead, so a test copy never touches yours."""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QSettings, QStandardPaths
from redactor_common.core import app_paths


def open_settings(path: Optional[str] = None) -> QSettings:
    if path is None:
        override = app_paths.config_override()
        folder = str(override) if override is not None else \
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "dossier.ini")
    return QSettings(path, QSettings.Format.IniFormat)

"""The settings file of the program: a plain ``dossier.ini`` in the user's config folder (never the registry). The window and the stand-alone
picture viewer open the same one, so a look chosen in one is seen by the other."""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QSettings, QStandardPaths


def open_settings(path: Optional[str] = None) -> QSettings:
    if path is None:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "dossier.ini")
    return QSettings(path, QSettings.Format.IniFormat)

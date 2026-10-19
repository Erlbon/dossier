"""Start Dossier: ``python -m dossier`` or the ``dossier`` command."""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    from PyQt6.QtWidgets import QApplication

    from ..core.platform import set_app_id
    from .appicon import app_icon
    from .main_window import MainWindow

    set_app_id("Erlbon.Dossier")

    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("Dossier")
    app.setOrganizationName("Erlbon")
    app.setWindowIcon(app_icon())                 # every window of the program, the viewer and notepad too
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

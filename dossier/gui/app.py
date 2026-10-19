"""Start Dossier: ``python -m dossier`` or the ``dossier`` command."""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    from PyQt6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(list(sys.argv if argv is None else argv))
    app.setApplicationName("Dossier")
    app.setOrganizationName("Erlbon")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

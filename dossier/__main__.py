"""``python -m dossier``, or ``python dossier/__main__.py`` from a checkout, or ``python path/to/dossier``."""
import os
import sys

if __package__ in (None, ""):                      # started as a file: the folder above this one must be on the path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dossier.gui.app import main

raise SystemExit(main())

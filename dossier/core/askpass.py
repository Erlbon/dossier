"""The helper program ``ssh`` runs when it needs a password: it prints the one Dossier put in its environment.

OpenSSH asks for a password or a key passphrase by running the program named in ``SSH_ASKPASS``. Dossier never puts a password on a
command line or in a file: it is handed to the single ``ssh`` process through the environment variable below, and this helper prints it.
It answers only the questions about a password or passphrase; for anything else (a yes/no question about a host key, which Dossier has
already settled) it prints nothing, so ssh gives up instead of guessing.
"""
from __future__ import annotations

import os
import sys

VARIABLE = "DOSSIER_SSH_PASSWORD"


def answer(prompt: str, environ=os.environ) -> bytes:
    text = prompt.lower()
    if "password" in text or "passphrase" in text or "verification code" in text:
        return environ.get(VARIABLE, "").encode("utf-8") + b"\n"
    return b""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    sys.stdout.buffer.write(answer(" ".join(a for a in argv if not a.startswith("--askpass"))))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

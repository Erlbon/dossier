"""A stand-in for ``ssh`` in the tests: it records how it was called, then either serves SFTP (by running OpenSSH's real ``sftp-server`` on
its own streams, as ``ssh -s host sftp`` would) or fails the way ssh does. Run as ``python fake_ssh.py <ssh arguments>``.

Environment: ``FAKE_SSH_LOG`` (a file to write the call to), ``FAKE_SSH_MODE`` (``serve``, ``deny``, ``refused``, ``silent``),
``FAKE_SFTP_SERVER`` (the sftp-server program).
"""
import json
import os
import subprocess
import sys
import time


def main() -> int:
    log = os.environ.get("FAKE_SSH_LOG")
    if log:
        keep = ("SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "DOSSIER_SSH_PASSWORD", "DISPLAY")
        with open(log, "w", encoding="utf-8") as f:
            json.dump({"args": sys.argv[1:], "env": {k: os.environ.get(k) for k in keep}}, f)
    mode = os.environ.get("FAKE_SSH_MODE", "serve")
    if mode == "deny":
        sys.stderr.write("user@host: Permission denied (publickey,password).\n")
        return 255
    if mode == "needs_password" and os.environ.get("DOSSIER_SSH_PASSWORD") != "pw":
        sys.stderr.write("user@host: Permission denied (publickey,password).\n")
        return 255
    if mode == "refused":
        sys.stderr.write("ssh: connect to host example port 22: Connection refused\n")
        return 255
    if mode == "silent":
        time.sleep(3)
        return 1
    return subprocess.call([os.environ["FAKE_SFTP_SERVER"]])


if __name__ == "__main__":
    raise SystemExit(main())

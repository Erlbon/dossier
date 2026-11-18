Dossier for Linux (x86-64; Debian 12 or newer, Ubuntu 22.04 or newer). A first test build.

To run it: unpack the archive anywhere you can write, then start dossier/dossier
    tar -xzf dossier-linux-x86_64-*.tar.gz
    ./dossier/dossier

If it does not start and says a Qt platform plugin could not be loaded, install the X11 cursor library:
    sudo apt install libxcb-cursor0

Good to know
- It does not update itself: Help > Check for Updates says whether there is a newer build and links to it.
- Open Terminal Here uses the first terminal program it finds (x-terminal-emulator, GNOME Terminal, Konsole, Xfce
  Terminal, kitty, Alacritty, xterm).
- dossier/dossier also runs the command line: dossier/dossier --help

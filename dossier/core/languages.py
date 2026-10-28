"""Which language a file is written in, from its name: for the notepad's syntax highlighting and folding (no Qt here)."""
from __future__ import annotations

import os
from typing import Optional

from .viewmodes import MARKDOWN_EXTENSIONS

HIGHLIGHT_LIMIT = 1_000_000          # characters; a bigger text is not highlighted (the lexer works on every edit)

# key: (name shown in the menu, extensions)
LANGUAGES = {
    "python": ("Python", (".py", ".pyw", ".pyi")),
    "javascript": ("JavaScript and TypeScript", (".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx")),
    "json": ("JSON", (".json", ".jsonc")),
    "html": ("HTML", (".html", ".htm", ".xhtml")),
    "xml": ("XML", (".xml", ".xsd", ".xsl", ".xslt", ".svg", ".csproj", ".vbproj", ".config", ".plist", ".ui", ".qrc", ".resx")),
    "css": ("CSS", (".css",)),
    "yaml": ("YAML", (".yml", ".yaml")),
    "sql": ("SQL", (".sql",)),
    "bash": ("Shell script", (".sh", ".bash", ".zsh")),
    "batch": ("Batch file", (".bat", ".cmd")),
    "cpp": ("C and C++", (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh")),
    "csharp": ("C#", (".cs",)),
    "java": ("Java", (".java",)),
    "ruby": ("Ruby", (".rb",)),
    "perl": ("Perl", (".pl", ".pm")),
    "lua": ("Lua", (".lua",)),
    "markdown": ("Markdown", MARKDOWN_EXTENSIONS),
    "properties": ("Settings file (ini, toml, properties)", (".ini", ".cfg", ".conf", ".toml", ".properties")),
    "diff": ("Diff", (".diff", ".patch")),
    "makefile": ("Makefile", (".mk",)),
    "cmake": ("CMake", (".cmake",)),
    "tex": ("TeX", (".tex",)),
}
FILENAMES = {"makefile": "makefile", "gnumakefile": "makefile", "cmakelists.txt": "cmake"}


def language_for(path: str) -> Optional[str]:
    """The language key for this file name, or None when it is not a kind that has highlighting."""
    name = os.path.basename(path).lower()
    if name in FILENAMES:
        return FILENAMES[name]
    for key, (_label, extensions) in LANGUAGES.items():
        if name.endswith(tuple(extensions)):
            return key
    return None


def label(key: str) -> str:
    return LANGUAGES[key][0] if key in LANGUAGES else key

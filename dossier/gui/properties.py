"""Files > Properties (Alt+Return): the facts of the selected items, and the metadata inside a file.

Step 1 of the metadata work is read only (docs/metadata-plan.md): the tabs show; nothing here can change a file.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                             QPlainTextEdit, QPushButton, QTabWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import metawrite
from ..core.filetags import CannotHoldTags, TagChange, apply_change, clean_tags
from ..core.properties import Gathered, gather
from .owned_dialog import OwnedDialog
from .background import run_in_background

KIND_TITLES = {"audio": "Audio tags", "comic": "ComicInfo", "video": "Video details"}
DIFFERENT = "(different)"
REMOVED = "(will be removed)"
# what the read-only reader calls the fields the form edits, so the "Also in the file" list shows only the rest
COVERED_BY_FORM = {"audio": {"title", "artist", "album", "albumartist", "track", "disc", "date", "genre", "composer"},
                   "comic": {"series", "number", "count", "volume", "title", "summary", "date", "writer", "penciller", "inker", "colorist", "letterer",
                             "coverartist", "editor", "publisher", "imprint", "genre", "tags", "languageiso", "agerating", "manga", "web"}}
LABELS = ("red", "orange", "yellow", "green", "blue", "purple", "grey")
KEEP = "(leave as it is)"


def split_tags(text: str) -> list:
    """The tags typed into a box: separated by commas or semicolons."""
    return clean_tags(text.replace(";", ",").split(","))


class PropertiesDialog(OwnedDialog):
    def __init__(self, parent, data: Gathered, known_tags=()) -> None:
        super().__init__(parent)
        self.setWindowTitle(data.title)
        self.setMinimumWidth(560)
        self.data = data
        self.known_tags = sorted(set(known_tags), key=str.casefold)
        self.change = None                                 # set by Save Tags: what to write
        self.meta_edits: dict = {}                         # set by Save Metadata: field key -> new value, only for what was changed
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        general = QWidget()
        form = QFormLayout(general)
        for fact in data.facts:
            value = QLabel(fact.value)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setWordWrap(True)
            form.addRow(fact.label, value)
        self.tabs.addTab(general, "General")
        self.meta_tab = None
        if data.edit_kind:
            self.meta_tab = self._edit_tab(data)
            self.tabs.addTab(self.meta_tab, KIND_TITLES.get(data.edit_kind, "Metadata"))
        elif data.meta is not None:
            self.tabs.addTab(self._metadata_tab(data.meta), KIND_TITLES.get(data.meta_kind, "Metadata"))
        self.tags_tab = None
        if data.tags or data.tags_reason:
            self.tags_tab = self._tags_tab(data)
            self.tabs.addTab(self.tags_tab, "Tags")
        buttons = QDialogButtonBox()
        self.save_button = QPushButton("Save Tags")
        self.save_button.setAutoDefault(False)
        self.save_button.clicked.connect(self._save_tags)
        buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.meta_button = QPushButton("Save Metadata")
        self.meta_button.setAutoDefault(False)
        self.meta_button.clicked.connect(self._save_metadata)
        buttons.addButton(self.meta_button, QDialogButtonBox.ButtonRole.ActionRole)
        self.tabs.currentChanged.connect(self._tab_changed)
        self._tab_changed()                                                         # after addButton: adding re-shows a button
        self.copy_button = QPushButton("Copy All")
        self.copy_button.setAutoDefault(False)
        self.copy_button.clicked.connect(self.copy_all)
        buttons.addButton(self.copy_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda b: self.accept() if b not in (self.copy_button, self.save_button, self.meta_button) else None)
        layout.addWidget(buttons)

    def _tab_changed(self, *_args) -> None:
        """Each tab has its own save button: Save Tags on the Tags tab, Save Metadata on the tab with the tags inside the file."""
        current = self.tabs.currentWidget()
        self.save_button.setVisible(current is self.tags_tab and bool(self.data.tags) and self.data.tags_can_write)
        self.meta_button.setVisible(current is self.meta_tab and self.meta_tab is not None and not self.data.edit_reason)

    # the tab for the tags inside the file --------------------------------------------------------------------------------
    def _edit_tab(self, data: Gathered) -> QWidget:
        """The tags of an mp3 (or flac, ogg, opus, m4a) or the ComicInfo of a cbz as a form. A field every file has in common shows its value; one
        that differs shows (different) and is left alone unless something is typed in it (then every file gets it). The little x takes a field
        away from every file. Only changed fields are written; what the form does not show (cover art, lyrics, technical facts) stays as it is."""
        page = QWidget()
        box = QVBoxLayout(page)
        if data.edit_reason:
            note = QLabel(data.edit_reason)
            note.setWordWrap(True)
            box.addWidget(note)
        many = len(data.edit_paths) > 1
        form = QFormLayout()
        self.edit_rows: dict = {}                       # key -> (line edit, clear button, initial value or None, multi-line?)
        self.cleared: set = set()
        for key, label in metawrite.fields_for(data.edit_kind):
            multi = key == "Summary"
            initial = data.edit_values.get(key, "") if data.edit_values else ""
            line = QPlainTextEdit() if multi else QLineEdit()
            if multi:
                line.setFixedHeight(64)
            clear = QToolButton()
            clear.setText("x")
            clear.setToolTip("Take this field away from " + ("every file" if many else "the file"))
            clear.setAutoRaise(True)
            clear.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            row = QHBoxLayout()
            row.addWidget(line, 1)
            row.addWidget(clear)
            form.addRow(label, row)
            self.edit_rows[key] = (line, clear, initial, multi)
            self._set_line(key, initial)
            line.textChanged.connect(lambda *_a, k=key: self._edit_changed(k))
            clear.clicked.connect(lambda _c=False, k=key: self._clear_field(k))
            if data.edit_reason or not data.edit_values:
                line.setEnabled(False)
                clear.setEnabled(False)
        box.addLayout(form)
        self.edit_summary = QLabel()
        self.edit_summary.setWordWrap(True)
        box.addWidget(self.edit_summary)
        also = self._also_in_the_file(data)
        if also is not None:
            box.addWidget(also, 1)
        else:
            box.addStretch(1)
        self._edit_changed(None)
        return page

    def _text_of(self, key: str) -> str:
        line, _clear, _initial, multi = self.edit_rows[key]
        return line.toPlainText() if multi else line.text()

    def _set_line(self, key: str, initial) -> None:
        line, _clear, _initial, multi = self.edit_rows[key]
        blocked = line.blockSignals(True)
        (line.setPlainText if multi else line.setText)("" if initial is None else initial)
        line.setPlaceholderText(DIFFERENT if initial is None else "")
        line.blockSignals(blocked)

    def _clear_field(self, key: str) -> None:
        line, _clear, _initial, multi = self.edit_rows[key]
        self.cleared.add(key)
        blocked = line.blockSignals(True)
        (line.setPlainText if multi else line.setText)("")
        line.setPlaceholderText(REMOVED)
        line.blockSignals(blocked)
        self._edit_changed(key)

    def _edit_changed(self, key) -> None:
        if key is not None and self._text_of(key) != "":
            self.cleared.discard(key)                              # something was typed again: it is no longer a removal
            self.edit_rows[key][0].setPlaceholderText(DIFFERENT if self.edit_rows[key][2] is None else "")
        edits = self.metadata_changes()
        for k, (line, _clear, _initial, _multi) in self.edit_rows.items():
            font = line.font()
            font.setBold(k in edits)                               # a changed field is marked in bold, with no colour of its own
            line.setFont(font)
        files = len(self.data.edit_paths)
        problems = len(self.data.edit_problems)
        text = (f"{len(edits)} field{'s' if len(edits) != 1 else ''} changed on {files} file{'s' if files != 1 else ''}" if edits
                else "Nothing changed. A field left alone is not touched.")
        if problems and files:
            text += f"  {problems} file{'s' if problems != 1 else ''} cannot be changed and will be left out."
        self.edit_summary.setText(text)

    def metadata_changes(self) -> dict:
        """The fields the form changes: key -> new text (empty: take the field away). A field left as it was is not in it."""
        if not self.data.edit_kind or self.data.edit_reason or not hasattr(self, "edit_rows"):
            return {}
        out = {}
        for key, (_line, _clear, initial, _multi) in self.edit_rows.items():
            text = self._text_of(key).strip()
            if key in self.cleared:
                out[key] = ""
            elif initial is None:
                if text:
                    out[key] = text
            elif text != initial:
                out[key] = text
        return out

    def _also_in_the_file(self, data: Gathered):
        """What the file carries that the form does not edit (length, bitrate, cover art, lyrics...), read only, for a single file."""
        if data.meta is None or len(data.edit_paths) != 1:
            return None
        covered = COVERED_BY_FORM.get(data.edit_kind, set())
        rest = [f for f in data.meta.fields if f.key not in covered]
        if not rest:
            return None
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Also in the file (not edited here)", "Value"])
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setColumnWidth(0, 230)
        for f in rest:
            item = QTreeWidgetItem([f.label, f.value])
            item.setToolTip(1, f.value)
            tree.addTopLevelItem(item)
        tree.setMaximumHeight(170)
        return tree

    def _save_metadata(self) -> None:
        self.meta_edits = self.metadata_changes()
        if self.meta_edits:
            self.accept()

    def _metadata_tab(self, meta) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        if meta.error:
            note = QLabel(meta.error)
            note.setWordWrap(True)
            box.addWidget(note)
        tree = QTreeWidget()
        tree.setColumnCount(2)
        tree.setHeaderLabels(["Field", "Value"])
        tree.setRootIsDecorated(False)
        tree.setUniformRowHeights(True)
        tree.setColumnWidth(0, 190)
        bold = QFont()
        bold.setBold(True)
        for group in meta.groups():
            top = QTreeWidgetItem([group])
            top.setFont(0, bold)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            tree.addTopLevelItem(top)
            for f in meta.fields:
                if f.group == group:
                    child = QTreeWidgetItem([f.label, f.value])
                    child.setToolTip(1, f.value)
                    top.addChild(child)
            top.setExpanded(True)
        box.addWidget(tree)
        hint = QLabel("Read only for now: changing these values comes in a later step.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.tree = tree
        return page

    # the Tags tab ---------------------------------------------------------------------------------------------------
    def _tags_tab(self, data: Gathered) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        if data.tags_reason:
            note = QLabel(data.tags_reason)
            note.setWordWrap(True)
            box.addWidget(note)
        self.many = len(data.paths) > 1
        if not data.tags:
            box.addStretch(1)
            return page
        form = QFormLayout()
        writable = data.tags_can_write
        records = list(data.tags.values())
        self.rating = QComboBox()
        self.label = QComboBox()
        if self.many:
            common = [t for t in records[0].tags if all(r.has(t) for r in records)]
            some = sorted({t for r in records for t in r.tags if not all(x.has(t) for x in records)}, key=str.casefold)
            summary = QLabel("On every item: " + (", ".join(common) or "none") + chr(10) + "On some: " + (", ".join(some) or "none"))
            summary.setWordWrap(True)
            form.addRow("Tags now", summary)
            self.add_edit, self.remove_edit = QLineEdit(), QLineEdit()
            self.add_edit.setPlaceholderText("tags to add to every item, separated by commas")
            self.remove_edit.setPlaceholderText("tags to take off every item")
            form.addRow("Add", self.add_edit)
            form.addRow("Remove", self.remove_edit)
            self.rating.addItem(KEEP, None)
            self.label.addItem(KEEP, None)
        else:
            current = records[0]
            self.tag_edit = QLineEdit(", ".join(current.tags))
            self.tag_edit.setPlaceholderText("holiday, 2019, family")
            form.addRow("Tags", self.tag_edit)
            self.pick = None
            if self.known_tags:
                pick = QComboBox()
                pick.addItem("Add a tag you used before...", "")
                for t in self.known_tags:
                    pick.addItem(t, t)
                pick.activated.connect(lambda i, p=pick: (self._pick(p.itemData(i)), p.setCurrentIndex(0)))
                form.addRow("", pick)
                self.pick = pick
            self.note_edit = QPlainTextEdit(current.note)
            self.note_edit.setFixedHeight(70)
        self.rating.addItem("No rating", 0)
        for n in range(1, 6):
            self.rating.addItem(chr(0x2605) * n, n)
        self.label.addItem("No label", "")
        for name in LABELS:
            self.label.addItem(name.capitalize(), name)
        if not self.many:
            self.rating.setCurrentIndex(max(0, self.rating.findData(current.rating)))
            self.label.setCurrentIndex(max(0, self.label.findData(current.label)))
        form.addRow("Rating", self.rating)
        form.addRow("Label", self.label)
        if not self.many:
            form.addRow("Note", self.note_edit)
        box.addLayout(form)
        widgets = ([self.add_edit, self.remove_edit] if self.many else [self.tag_edit, self.note_edit]) + [self.rating, self.label]
        if not self.many and self.pick is not None:
            widgets.append(self.pick)
        for w in widgets:
            w.setEnabled(writable)
        box.addStretch(1)
        hint = QLabel("Tags are kept on the file itself (no database). They are lost when a file is copied by a program that "
                      "ignores them, or sent by mail or to most cloud services.")
        hint.setWordWrap(True)
        box.addWidget(hint)
        return page

    def _pick(self, tag) -> None:
        if tag:
            self.tag_edit.setText(", ".join(clean_tags(split_tags(self.tag_edit.text()) + [tag])))

    def tag_change(self) -> TagChange:
        """What the Tags tab asks for (empty when nothing was changed)."""
        data = self.data
        if not data.tags or not data.tags_can_write:
            return TagChange()
        if self.many:
            return TagChange(add=split_tags(self.add_edit.text()), remove=split_tags(self.remove_edit.text()),
                             rating=self.rating.currentData(), label=self.label.currentData())
        current = next(iter(data.tags.values()))
        change = TagChange()
        typed = split_tags(self.tag_edit.text())
        if [t.casefold() for t in typed] != [t.casefold() for t in current.tags]:
            change.replace = typed
        if self.rating.currentData() != current.rating:
            change.rating = self.rating.currentData()
        if self.label.currentData() != current.label:
            change.label = self.label.currentData()
        if self.note_edit.toPlainText() != current.note:
            change.note = self.note_edit.toPlainText()
        return change

    def _save_tags(self) -> None:
        self.change = self.tag_change()
        self.accept()

    def text(self) -> str:
        lines = [self.data.title, ""]
        lines += [f"{f.label}: {f.value}" for f in self.data.facts]
        if self.data.meta is not None:
            lines.append("")
            for g in self.data.meta.groups():
                lines.append(g)
                lines += [f"  {f.label}: {f.value}" for f in self.data.meta.fields if f.group == g]
        return chr(10).join(lines)

    def copy_all(self) -> None:
        QApplication.clipboard().setText(self.text())


class PropertiesMixin:
    """Part of ``MainWindow``."""

    @property
    def _known_tags(self) -> set:
        """Every tag seen or saved in this session (the "used before" list). Nothing is stored."""
        return self.__dict__.setdefault("_known_tag_set", set())

    def show_properties(self) -> None:
        panel = self.active
        if panel.is_home:
            self._say("The Home page lists shortcuts: open a folder to see the properties of its items")
            return
        paths = [p for p in panel.targets() if self.fs.basename(p) != ".."]
        if not paths:
            self._say("Nothing to show: mark items or put the cursor on one")
            return

        def work(progress, cancel):
            progress(0, 0)
            return gather(self.fs, paths, cancel)

        def finished(data) -> None:
            for t in data.tags.values():
                self._known_tags.update(t.tags)
            dlg = PropertiesDialog(self, data, self._known_tags)
            self._show_properties_dialog(dlg)
            if dlg.change is not None and not dlg.change.is_empty():
                self._write_tags(list(data.paths), dlg.change)
            if dlg.meta_edits:
                self._change_metadata(list(data.edit_paths), dlg.meta_edits, data.edit_kind)

        run_in_background(self, self.cmd_runner, "Reading properties", work, on_result=finished, tracked=self._size_jobs,
                          indeterminate=True, failed_title="Properties")

    def _show_properties_dialog(self, dlg) -> None:       # a seam for tests
        dlg.exec()

    def _write_tags(self, paths: list, change) -> None:
        """Save the change on every item, on a thread; say what could not be done."""
        failed: list = []

        def work(progress, cancel):
            saved = 0
            for i, p in enumerate(paths):
                progress(i, len(paths))
                try:
                    t = apply_change(p, change)
                    self._known_tags.update(t.tags)
                    saved += 1
                except CannotHoldTags:
                    failed.append((p, "this drive cannot store tags"))
                except OSError as e:
                    failed.append((p, e.strerror or str(e)))
            return saved

        def finished(saved: int) -> None:
            text = f"Tags saved on {saved} item{'s' if saved != 1 else ''}"
            if failed:
                text += f"; {len(failed)} could not be changed"
                self.dialogs.info("Tags", chr(10).join(f"{self.fs.basename(p)}: {why}" for p, why in failed[:10]))
            self._say(text)
            for panel in (self.left, self.right):
                panel.refresh_tags()                     # the Tags and Rating columns show what was just saved

        run_in_background(self, self.cmd_runner, "Saving tags", work, on_result=finished, tracked=self._size_jobs,
                          failed_title="Tags")

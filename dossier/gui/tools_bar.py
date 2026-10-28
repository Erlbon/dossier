"""The tools bar: a row between the menu bar and the panels with the programs the user keeps one click away, and folders of them.

A button starts a program on the marked items (or the item under the cursor); a folder button opens a drop-down. The bar is edited
from its own right-click menu (Add Program, Add Folder, Edit, Remove) and from Manage Tools, a tree where items are dragged into
folders and reordered. A program file dropped on the bar becomes a tool. The list lives in the settings file (``tools/bar``).
"""
from __future__ import annotations

import os
from typing import Optional

from PyQt6.QtCore import QFileInfo, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFileIconProvider, QFormLayout,
                             QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QToolButton,
                             QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import startmenu as SM
from ..core import tools as T
from ..core.drives import is_network_path
from . import frost, icon_set, theme
from .owned_dialog import OwnedDialog
from .background import run_in_background
from .bar_grip import BarGrip

PROGRAM_EXTENSIONS = (".exe", ".com", ".bat", ".cmd", ".lnk", ".ps1", ".msi", ".appref-ms", ".jar", ".py", ".sh")


def program_icon(command: str) -> QIcon:
    """The program's own icon; nothing for a program on a network drive (asking would wait for the share)."""
    try:
        if command and not is_network_path(command) and os.path.isabs(command):
            return QFileIconProvider().icon(QFileInfo(command))          # made when asked: not before the application exists
    except Exception:   # noqa: BLE001 -- an icon is a nicety
        pass
    return QIcon()


def folder_icon() -> QIcon:
    """The folder in the accent colour of the current scheme, like the folders in the file lists."""
    return icon_set.icon("folder", theme.current()["accent"])


class StartMenuDialog(OwnedDialog):
    """The programs of the Windows Start menu as a tree with a search box; choose one, or go on to type the program in by hand."""

    def __init__(self, parent, tree: list) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a Program")
        self.setMinimumSize(480, 520)
        self.tree_data = tree
        self.other = False
        self.picked: Optional[SM.Node] = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose a program from the Start menu:"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._fill)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(lambda item, _c: self._choose(item))
        self.tree.itemSelectionChanged.connect(self._selection)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.addButton("Add", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setEnabled(False)
        manual = buttons.addButton("Other program...", QDialogButtonBox.ButtonRole.ActionRole)
        manual.setAutoDefault(False)
        manual.clicked.connect(self._manual)
        buttons.accepted.connect(lambda: self._choose(self.tree.currentItem()))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._fill("")

    def _fill(self, text: str) -> None:
        self.tree.clear()
        shown = SM.filter_tree(self.tree_data, text)
        searching = bool(text.strip())

        def add(parent, nodes) -> None:
            for n in nodes:
                item = QTreeWidgetItem(parent if parent is not None else self.tree, [n.name])
                item.setData(0, Qt.ItemDataRole.UserRole, n)
                if n.is_group:
                    item.setIcon(0, folder_icon())
                    add(item, n.children)
                    item.setExpanded(searching)
                else:
                    item.setIcon(0, program_icon(n.path))
        add(None, shown)

    def _selection(self) -> None:
        item = self.tree.currentItem()
        node = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        self.ok.setEnabled(node is not None and not node.is_group)

    def _choose(self, item) -> None:
        node = item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        if node is None or node.is_group:
            return
        self.picked = node
        self.accept()

    def _manual(self) -> None:
        self.other = True
        self.accept()


class ToolDialog(OwnedDialog):
    """Add or edit one program: name, program, arguments, start folder, and where it goes."""

    def __init__(self, parent, tool: Optional[T.Tool] = None, places: Optional[list] = None, suggestions: Optional[list] = None,
                 title: str = "Add a Program") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.suggestions = list(suggestions or [])
        if self.suggestions and tool is None:
            self.suggest = QComboBox()
            self.suggest.addItem("Start from a program found on this computer...", None)
            for s in self.suggestions:
                self.suggest.addItem(s.name, s)
            self.suggest.activated.connect(self._suggested)
            form.addRow("", self.suggest)
        self.name = QLineEdit(tool.name if tool else "")
        self.command = QLineEdit(tool.command if tool else "")
        browse = QPushButton("Browse...")
        browse.setAutoDefault(False)
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.command, 1)
        row.addWidget(browse)
        self.args = QLineEdit(tool.args if tool else "")
        self.args.setPlaceholderText('for example:  --open {files}      "{dir}"')
        self.start_in = QLineEdit(tool.start_in if tool else "")
        self.start_in.setPlaceholderText("empty: the folder of the active panel")
        form.addRow("Name", self.name)
        form.addRow("Program", row)
        form.addRow("Arguments", self.args)
        form.addRow("Start in", self.start_in)
        self.where = None
        if places:
            self.where = QComboBox()
            for label, _lst in places:
                self.where.addItem(label)
            form.addRow("Put it in", self.where)
        layout.addLayout(form)
        help_text = "In the arguments:  " + "   ".join(f"{p}" for p, _why in T.PLACEHOLDERS) + \
                    "\n{files} = every marked item, or the one under the cursor; {file} = the first; {name} = its name;\n" \
                    "{dir} = this panel's folder; {other} = the other panel's folder."
        hint = QLabel(help_text)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.problem = QLabel()
        self.problem.setWordWrap(True)
        layout.addWidget(self.problem)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.ok = buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _suggested(self, index: int) -> None:
        s = self.suggest.itemData(index)
        if s is not None:
            self.name.setText(s.name)
            self.command.setText(s.command)
            self.args.setText(s.args)

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "Choose a program", self.command.text())
        if path:
            self.command.setText(os.path.normpath(path))
            if not self.name.text().strip():
                self.name.setText(os.path.splitext(os.path.basename(path))[0])

    def _accept(self) -> None:
        try:
            self.tool()
        except T.BadTool as e:
            self.problem.setText(f"Cannot save: {e}.")
            return
        self.accept()

    def tool(self) -> T.Tool:
        name, command = self.name.text().strip(), self.command.text().strip().strip('"')
        if not name:
            raise T.BadTool("give it a name")
        if not command:
            raise T.BadTool("say which program to start")
        T.check_args(self.args.text())
        return T.Tool(name, command, self.args.text().strip(), self.start_in.text().strip())

    def place_index(self) -> int:
        return self.where.currentIndex() if self.where is not None else 0


class FolderDialog(OwnedDialog):
    def __init__(self, parent, name: str = "", places: Optional[list] = None, title: str = "Add a Folder") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QFormLayout(self)
        self.name = QLineEdit(name)
        layout.addRow("Name", self.name)
        self.where = None
        if places:
            self.where = QComboBox()
            for label, _lst in places:
                self.where.addItem(label)
            layout.addRow("Put it in", self.where)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _accept(self) -> None:
        if self.name.text().strip():
            self.accept()

    def place_index(self) -> int:
        return self.where.currentIndex() if self.where is not None else 0


class ManageDialog(OwnedDialog):
    """The whole bar as a tree: drag items into folders and into order, edit, remove."""

    def __init__(self, parent, items: list, edit_tool, edit_folder) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Tools")
        self.resize(640, 460)
        self._edit_tool, self._edit_folder = edit_tool, edit_folder
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Drag items into folders and into the order you want."))
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Name", "Program", "Arguments"])
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 250)
        self._fill(self.tree.invisibleRootItem(), items)
        self.tree.expandAll()
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, slot in (("Edit...", self._edit), ("Remove", self._remove), ("Add Folder", self._add_folder),
                           ("Add Separator", self._add_separator), ("Up", lambda: self._move(-1)), ("Down", lambda: self._move(1))):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.addButton("Save", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _fill(self, parent, items: list) -> None:
        for it in items:
            node = QTreeWidgetItem(parent)
            self._show(node, it)
            if isinstance(it, T.Folder):
                self._fill(node, it.items)

    def _show(self, node: QTreeWidgetItem, it) -> None:
        node.setData(0, Qt.ItemDataRole.UserRole, it)
        if isinstance(it, T.Tool):
            node.setText(0, it.name)
            node.setText(1, it.command)
            node.setText(2, it.args)
            node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)
        elif isinstance(it, T.Folder):
            node.setText(0, it.name)
            node.setIcon(0, folder_icon())
        else:
            node.setText(0, "-------- separator --------")
            node.setFlags(node.flags() & ~Qt.ItemFlag.ItemIsDropEnabled)

    def _edit(self) -> None:
        node = self.tree.currentItem()
        if node is None:
            return
        it = node.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(it, T.Tool):
            changed = self._edit_tool(it)
            if changed is not None:
                self._show(node, changed)
        elif isinstance(it, T.Folder):
            name = self._edit_folder(it.name)
            if name:
                it.name = name
                self._show(node, it)

    def _remove(self) -> None:
        node = self.tree.currentItem()
        if node is not None:
            (node.parent() or self.tree.invisibleRootItem()).removeChild(node)

    def _add_folder(self) -> None:
        name = self._edit_folder("")
        if name:
            node = QTreeWidgetItem(self.tree.invisibleRootItem())
            self._show(node, T.Folder(name))

    def _add_separator(self) -> None:
        node = QTreeWidgetItem(self.tree.invisibleRootItem())
        self._show(node, T.Separator())

    def _move(self, step: int) -> None:
        node = self.tree.currentItem()
        if node is None:
            return
        parent = node.parent() or self.tree.invisibleRootItem()
        i = parent.indexOfChild(node)
        j = i + step
        if 0 <= j < parent.childCount():
            parent.takeChild(i)
            parent.insertChild(j, node)
            self.tree.setCurrentItem(node)

    def items(self) -> list:
        def read(parent) -> list:
            out = []
            for i in range(parent.childCount()):
                node = parent.child(i)
                it = node.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(it, T.Folder):
                    it = T.Folder(it.name, read(node))
                out.append(it)
            return out
        return read(self.tree.invisibleRootItem())


class ToolsBar(QWidget):
    run_requested = pyqtSignal(object)            # a Tool: start it
    context_requested = pyqtSignal(object, object)   # (global position, path of the item under it, () for the bar itself)
    program_dropped = pyqtSignal(str)             # a program file was dropped on the bar
    drag_moved = pyqtSignal(object)               # the grip is being dragged (global position)
    drag_dropped = pyqtSignal(object)             # the grip was let go there

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("toolsbar")
        self.setAcceptDrops(True)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(6, 2, 6, 2)
        self._row.setSpacing(4)
        self.items: list = []
        self.buttons: list = []
        self.place = "below_menu"                 # set by the window (core/barplace.py)
        self.wanted_width = 0                     # in the menu bar's row: the room the menus leave (the menu bar sizes a corner widget by its hint)
        self.grip = BarGrip(self)
        self.grip.dragging.connect(self.drag_moved.emit)
        self.grip.dropped.connect(self.drag_dropped.emit)
        self.setMinimumHeight(30)
        self.restyle()

    def sizeHint(self):
        hint = super().sizeHint()
        if self.place == "menu_row" and self.wanted_width:
            hint.setWidth(max(hint.width(), self.wanted_width))
        return hint

    def set_place(self, place: str) -> None:
        """Where the bar sits decides which edge it draws: a line under it, above it, or none (in the menu bar's row)."""
        self.place = place
        self.setMinimumHeight(0 if place == "menu_row" else 30)
        self.restyle()

    def restyle(self) -> None:
        """A bar with its own background and a line under it, so it is seen even when it is empty."""
        t = theme.current()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        edge = {"below_menu": f"border-bottom:1px solid {t['line']};", "bottom": f"border-top:1px solid {t['line']};"}.get(self.place, "")
        self.setStyleSheet(f"#toolsbar{{background:{frost.fill(t['card'])};{edge}}}"
                           f"#toolsbar QToolButton{{color:{t['fg']};padding:2px 8px;border:none;border-radius:4px;}}"
                           f"#toolsbar QToolButton:hover{{background:{t['line']};}}"
                           f"#toolsbar QToolButton::menu-indicator{{image:none;}}"
                           f"#toolsbar QMenu{{background:{t['card']};color:{t['fg']};border:1px solid {t['line']};padding:3px;}}"
                           f"#toolsbar QMenu::item{{padding:4px 22px 4px 8px;border-radius:3px;}}"
                           f"#toolsbar QMenu::item:selected{{background:{t['accent']};color:{t['accent_fg']};}}"
                           f"#toolsbar QMenu::item:disabled{{color:{t['dim']};}}"
                           f"#toolsbar QMenu::separator{{height:1px;background:{t['line']};margin:3px 6px;}}"
                           f"#toolsbar QLabel{{color:{t['dim']};}}")
        if self.buttons or self.items:                          # the folder icons are tinted with the scheme: make them again
            self.set_items(self.items)

    def set_items(self, items: list) -> None:
        self.items = items
        for b in self.buttons:
            b.setParent(None)
            b.deleteLater()
        self.buttons = []
        while self._row.count():
            self._row.takeAt(0)
        self._row.addWidget(self.grip)
        for i, it in enumerate(items):
            self._add_widget(self._widget_for(it, (i,)))
        if not items:
            hint = QLabel("Your programs go here: press + or right-click this bar to add one")
            hint.setObjectName("toolshint")
            self._add_widget(hint)
        self.add_button = QToolButton()                         # always there, like the + of a browser's bookmarks bar
        self.add_button.setObjectName("toolsadd")
        self.add_button.setText("+")
        self.add_button.setAutoRaise(True)
        self.add_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.add_button.setToolTip("Add a program or a folder of programs to this bar")
        self.add_button.clicked.connect(lambda: self.context_requested.emit(self.add_button.mapToGlobal(self.add_button.rect().bottomLeft()), ()))
        self._add_widget(self.add_button)
        self._row.addStretch(1)

    def _add_widget(self, w: QWidget) -> None:
        self._row.addWidget(w)
        self.buttons.append(w)

    def _widget_for(self, it, path: tuple) -> QWidget:
        if isinstance(it, T.Separator):
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFrameShadow(QFrame.Shadow.Sunken)
            return line
        b = QToolButton()
        b.setAutoRaise(True)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        b.customContextMenuRequested.connect(lambda pos, w=b, p=path: self.context_requested.emit(w.mapToGlobal(pos), p))
        if isinstance(it, T.Folder):
            b.setText(it.name)
            b.setIcon(folder_icon())
            b.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            b.setMenu(self._menu_for(it.items))
            b.setToolTip(f"{it.name}: {len(it.items)} item{'s' if len(it.items) != 1 else ''}")
        else:
            b.setText(it.name)
            b.setIcon(program_icon(it.command))
            b.setToolTip(f"{it.command} {it.args}".strip())
            b.clicked.connect(lambda _c=False, t=it: self.run_requested.emit(t))
        return b

    def _menu_for(self, items: list) -> QMenu:
        menu = QMenu(self)
        for it in items:
            if isinstance(it, T.Separator):
                menu.addSeparator()
            elif isinstance(it, T.Folder):
                sub = self._menu_for(it.items)
                sub.setTitle(it.name)
                sub.setIcon(folder_icon())
                menu.addMenu(sub)
            else:
                action = QAction(it.name, menu)
                action.setIcon(program_icon(it.command))
                action.setToolTip(f"{it.command} {it.args}".strip())
                action.triggered.connect(lambda _c=False, t=it: self.run_requested.emit(t))
                menu.addAction(action)
        if not items:
            menu.addAction("(empty)").setEnabled(False)
        return menu

    def contextMenuEvent(self, event) -> None:
        self.context_requested.emit(event.globalPos(), ())
        event.accept()

    # a program file dropped on the bar --------------------------------------------------------------------------------------
    def _dropped_program(self, mime) -> str:
        if not mime.hasUrls():
            return ""
        for url in mime.urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(PROGRAM_EXTENSIONS):
                return os.path.normpath(path)
        return ""

    def dragEnterEvent(self, event) -> None:
        if self._dropped_program(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        path = self._dropped_program(event.mimeData())
        if not path:
            event.ignore()
            return
        event.acceptProposedAction()
        self.program_dropped.emit(path)


class ToolsBarMixin:
    """Part of ``MainWindow``."""

    SETTING = "tools/bar"
    tool_starter = None                           # tests put a recorder here: no program is started

    def _load_tools(self) -> list:
        return T.loads(str(self.settings.value(self.SETTING, "") or ""))

    def set_tools(self, items: list) -> None:
        self.settings.setValue(self.SETTING, T.dumps(items))
        self.tools_bar.set_items(items)

    @property
    def tools(self) -> list:
        return self.tools_bar.items

    def build_tools_bar(self) -> ToolsBar:
        bar = ToolsBar()
        bar.run_requested.connect(self.run_tool)
        bar.context_requested.connect(self.show_tools_menu)
        bar.program_dropped.connect(self.add_program_from_file)
        bar.drag_moved.connect(self._tools_bar_dragging)
        bar.drag_dropped.connect(self._tools_bar_dropped)
        bar.set_items(self._load_tools())
        return bar

    def set_tools_bar_visible(self, on: bool) -> None:
        self.settings.setValue("view/tools_bar", "true" if on else "false")
        self.tools_bar.setVisible(on)

    # running -----------------------------------------------------------------------------------------------------------------
    def run_tool(self, tool: T.Tool) -> None:
        panel = self.active
        files = [] if panel.is_home else panel.targets()
        try:
            T.launch(tool, files, panel.real_folder() if not panel.is_home else "", self.other.real_folder() if not self.other.is_home else "",
                     starter=self.tool_starter)
        except T.BadTool as e:
            self.dialogs.info(tool.name, f"This tool cannot run: {e}.")
        except OSError as e:
            self.dialogs.info(tool.name, f"Could not start {tool.command}: {e.strerror or e}")
        else:
            self._say(f"Started {tool.name}")

    # the bar's own menu ------------------------------------------------------------------------------------------------------
    def show_tools_menu(self, global_pos, path) -> None:
        menu = self.build_tools_menu(path)
        self._popup_menu(menu, global_pos)

    def build_tools_menu(self, path: tuple) -> QMenu:
        menu = QMenu(self)
        if path:
            menu.addAction("Edit...").triggered.connect(lambda: self.edit_tool_at(path))
            menu.addAction("Remove").triggered.connect(lambda: self.remove_tool_at(path))
            if len(path) == 1:
                left = menu.addAction("Move Left")
                left.setEnabled(path[0] > 0)
                left.triggered.connect(lambda: self.move_tool(path[0], -1))
                right = menu.addAction("Move Right")
                right.setEnabled(path[0] < len(self.tools) - 1)
                right.triggered.connect(lambda: self.move_tool(path[0], 1))
            menu.addSeparator()
        menu.addAction("Add Program...").triggered.connect(self.add_program)
        menu.addAction("Add Folder...").triggered.connect(self.add_tool_folder)
        menu.addAction("Add Separator").triggered.connect(self.add_separator)
        menu.addAction("Manage Tools...").triggered.connect(self.manage_tools)
        menu.addSeparator()
        menu.addAction("Hide the Tools Bar").triggered.connect(lambda: self.act_tools_bar.setChecked(False))
        return menu

    # changing the list -------------------------------------------------------------------------------------------------------
    def _ask_tool(self, dlg) -> bool:                       # seams for tests
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_folder(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_manage(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _ask_start_menu(self, dlg) -> bool:
        return dlg.exec() == QDialog.DialogCode.Accepted

    def add_program(self) -> None:
        """Start from the programs of the Windows Start menu (when there is one); "Other program..." goes on to the plain dialog."""
        def work(progress, cancel):
            progress(0, 0)
            return SM.scan(SM.roots(), cancel.check), T.suggestions()

        run_in_background(self, self.cmd_runner, "Looking for programs", work, on_result=self._programs_found,
                          tracked=self._size_jobs, indeterminate=True, failed_title="Add a Program")

    def _programs_found(self, found) -> None:
        tree, suggestions = found
        if tree:
            dlg = StartMenuDialog(self, tree)
            if not self._ask_start_menu(dlg):
                return
            if dlg.picked is not None:
                self._add_program_dialog(T.Tool(dlg.picked.name, dlg.picked.path), suggestions)
                return
        self._add_program_dialog(None, suggestions)

    def add_program_from_file(self, path: str) -> None:
        name = os.path.splitext(os.path.basename(path))[0]
        self._add_program_dialog(T.Tool(name, path), [])

    def _add_program_dialog(self, tool, suggestions) -> None:
        dlg = ToolDialog(self, tool if tool is not None and tool.command else None, T.places(self.tools), suggestions)
        if not self._ask_tool(dlg):
            return
        new = dlg.tool()
        items = list(self.tools)
        T.places(items)[dlg.place_index()][1].append(new)
        self.set_tools(items)
        self._say(f"Added {new.name} to the tools bar")

    def add_tool_folder(self) -> None:
        dlg = FolderDialog(self, "", T.places(self.tools))
        if not self._ask_folder(dlg) or not dlg.name.text().strip():
            return
        items = list(self.tools)
        T.places(items)[dlg.place_index()][1].append(T.Folder(dlg.name.text().strip()))
        self.set_tools(items)

    def add_separator(self) -> None:
        self.set_tools(list(self.tools) + [T.Separator()])

    def edit_tool_at(self, path: tuple) -> None:
        items = list(self.tools)
        holder = T.container(items, path)
        it = holder[path[-1]]
        if isinstance(it, T.Tool):
            dlg = ToolDialog(self, it, None, None, "Edit the Program")
            if self._ask_tool(dlg):
                holder[path[-1]] = dlg.tool()
                self.set_tools(items)
        elif isinstance(it, T.Folder):
            dlg = FolderDialog(self, it.name, None, "Rename the Folder")
            if self._ask_folder(dlg) and dlg.name.text().strip():
                it.name = dlg.name.text().strip()
                self.set_tools(items)

    def remove_tool_at(self, path: tuple) -> None:
        items = list(self.tools)
        it = T.container(items, path)[path[-1]]
        if isinstance(it, T.Folder) and it.items and not self.dialogs.confirm(
                "Remove Folder", f"Remove the folder {it.name} and the {len(it.items)} item(s) in it from the tools bar? "
                                 "The programs themselves are not touched.", "Remove"):
            return
        del T.container(items, path)[path[-1]]
        self.set_tools(items)

    def move_tool(self, index: int, step: int) -> None:
        items = list(self.tools)
        j = index + step
        if 0 <= j < len(items):
            items[index], items[j] = items[j], items[index]
            self.set_tools(items)

    def manage_tools(self) -> None:
        def edit_tool(tool):
            dlg = ToolDialog(self, tool, None, None, "Edit the Program")
            return dlg.tool() if self._ask_tool(dlg) else None

        def edit_folder(name):
            dlg = FolderDialog(self, name, None, "Folder")
            return dlg.name.text().strip() if self._ask_folder(dlg) else ""

        dlg = ManageDialog(self, self.tools, edit_tool, edit_folder)
        if self._ask_manage(dlg):
            self.set_tools(dlg.items())

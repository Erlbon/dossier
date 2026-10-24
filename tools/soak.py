"""Soak test: use Dossier hard for a while and watch memory, handles, threads and object counts. Headless (offscreen), temp data only.

    python tools/soak.py [rounds]          (needs psutil; ACTIONS=0,1,... picks the actions, NAV=0 turns folder changes off, TRACE=1 profiles)

Each round changes both panels' folders and does one more thing: a tab opened and closed, select all, a sort, the view mode, a copy that
overwrites and a delete, a Health window opened and closed, a command typed, an undo, a refresh. A flat object count and flat memory mean a
window can stay open for weeks. It stands in for the real event loop by processing the widgets that were scheduled for deletion.
"""
import gc, os, random, shutil, sys, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import psutil
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from tests.test_gui_commander import FakeDialogs
from dossier.gui.main_window import MainWindow
from dossier.core.ops import Resolution

import tempfile
base = tempfile.mkdtemp(prefix="dossier-soak-")
random.seed(1)
folders = []
for i in range(60):
    d = os.path.join(base, "tree", f"folder{i:02}")
    os.makedirs(d, exist_ok=True)
    folders.append(d)
    for j in range(60):
        with open(os.path.join(d, f"file{j:03}.txt"), "w") as f:
            f.write("x" * random.randint(1, 3000))
os.makedirs(base + r"\dest", exist_ok=True)

dialogs = FakeDialogs()
dialogs.conflict_answer = Resolution.OVERWRITE
dialogs.confirm_answer = True
win = MainWindow(settings_path=base + r"\s.ini", start=(folders[0], base + r"\dest"), dialogs=dialogs, trasher=lambda p: os.remove(p) if os.path.isfile(p) else shutil.rmtree(p, ignore_errors=True))
win.show()
proc = psutil.Process()


from PyQt6.QtCore import QCoreApplication, QEvent


def pump(until=lambda: True, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)       # what the real event loop does with deleteLater()
        if not win.busy and until():
            return True
        time.sleep(0.002)
    return False


def goto(panel, path):
    panel.set_folder(path)
    pump(lambda: panel.path == path and not panel.loading)


def sample(label):
    gc.collect()
    mi = proc.memory_full_info()
    row = (label, round(mi.rss / 1048576, 1), round(mi.uss / 1048576, 1), proc.num_threads(), proc.num_handles(), len(gc.get_objects()),
           len(win._jobs), len(win._size_jobs), len(win._plans))
    print("%-10s rss %6.1f MB  uss %6.1f MB  threads %3d  handles %4d  objects %7d  jobs %d/%d/%d" % row, flush=True)
    return row


pump()
rows = [sample("start")]
ENABLED = set(int(x) for x in os.environ.get("ACTIONS", "0,1,2,3,4,5,6,7,8").split(",") if x != "")
N = int(sys.argv[1]) if len(sys.argv) > 1 else 600
t0 = time.time()
import tracemalloc
snap_a = None
for i in range(1, N + 1):
    if os.environ.get("TRACE") and i == 200:
        gc.collect()
        tracemalloc.start(12)
        snap_a = tracemalloc.take_snapshot()
    if os.environ.get("NAV", "1") == "1":
        goto(win.left, random.choice(folders))
        goto(win.right, random.choice(folders))
    r = i % 10
    if r not in ENABLED:
        r = -1
    if r == 0:
        win.left.new_tab(random.choice(folders))
        pump()
        win.left.close_tab(win.left.tabs.currentIndex())
    if r == 1:
        win.selection.clear()
        win.active.table.selectAll()
        win.select_all()
        win.selection.clear()
    if r == 2:
        win.active.table.sortByColumn(random.choice([0, 1, 2]), Qt.SortOrder.AscendingOrder)
    if r == 3:
        win.choose_mode("icons" if win.left.view_mode == "details" else "details", 64)
        pump()
    if r == 4:                                   # a copy, a conflict that is overwritten, and a delete
        entries = [win.left.model.entry_at(k) for k in range(win.left.model.entry_count())]
        files = [e.path for e in entries if e is not None and e.name.startswith("file")][:8]
        win.selection.clear()
        win.selection.add(files)
        win.copy()
        pump(timeout=10)
        win.active = win.right
        win.selection.clear()
        win.selection.add([os.path.join(base, "dest", os.path.basename(p)) for p in files])
        win.delete(permanent=True)
        pump(timeout=10)
        win.active = win.left
    if r == 5:
        from dossier.gui.health_window import HealthWindow
        w = HealthWindow(win, random.choice(folders), start=True)
        pump(lambda: w.report is not None, 8)
        w.close()
        w.deleteLater()
    if r == 6:
        win.cmdline.setText("echo hi")
        win.cmdline.remember("echo hi %d" % i)
        win.cmdline.clear()
    if r == 7:
        win.undo()
    if r == 8:
        win.left.refresh()
        win.right.refresh()
        pump()
    del dialogs.progress_boxes[:]                      # the test dialogs keep every progress box; the real ones are closed and freed
    del dialogs.confirms[:], dialogs.infos[:]
    if i % 100 == 0:
        rows.append(sample(f"iter {i}"))
print("elapsed %.0f s" % (time.time() - t0))
if snap_a is not None:
    gc.collect()
    snap_b = tracemalloc.take_snapshot()
    print("--- growth by line (iteration 200 to end) ---")
    for stat in snap_b.compare_to(snap_a, "lineno")[:14]:
        print(stat)
first, last = rows[1], rows[-1]
print("growth from iteration %s to %s: uss %+.1f MB, handles %+d, threads %+d, objects %+d" % (first[0], last[0], last[2] - first[2], last[4] - first[4], last[3] - first[3], last[5] - first[5]))
win.close()
shutil.rmtree(base, ignore_errors=True)

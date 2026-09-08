#!/usr/bin/env python3
"""
setup_check.py — verify this machine can run the HoMM3 map toolkit.

The toolkit has no third-party dependencies, so there is nothing for pip to
install. What can actually go wrong is a Python that is too old, a missing
tkinter (packaged separately on several Linux distributions), or toolkit files
that did not all get copied into the same folder. This script checks those
three things and tells you exactly what to do about anything it finds.

It installs nothing, downloads nothing and changes nothing.

    python3 setup_check.py            # check and report
    python3 setup_check.py --quiet    # exit status only, for scripts

Exit status is 0 if the toolkit is fully usable, 1 if the GUIs cannot run but
the command-line tools can, and 2 if nothing will run.
"""

import argparse
import importlib
import os
import platform
import sys

MIN_PYTHON = (3, 8)

TOOLKIT_FILES = [
    ("h3m.py", "the format: parsing, editing, writing"),
    ("h3m_render.py", "drawing code: palettes, tile index, hover text"),
    ("h3m_creatures.py", "reference data: AI values, stats, artifact classes"),
    ("h3m_balance.py", "balance model and auto-balance"),
    ("h3m_army.py", "army composition"),
    ("h3m_report.py", "HTML analysis report"),
    ("h3m_gui.py", "shared window used by both programs"),
    ("h3m_viewer.py", "read-only program"),
    ("h3m_editor.py", "editing program"),
]

STDLIB = [
    "argparse", "base64", "binascii", "collections", "csv", "gzip", "html",
    "json", "math", "os", "statistics", "struct", "sys", "tempfile",
    "traceback", "webbrowser", "zlib",
]

TK_HELP = {
    "linux": ("Debian / Ubuntu : sudo apt install python3-tk\n"
              "  Fedora / RHEL   : sudo dnf install python3-tkinter\n"
              "  Arch            : sudo pacman -S tk\n"
              "  openSUSE        : sudo zypper install python3-tk"),
    "darwin": ("Install Python from python.org, which bundles tkinter.\n"
               "  Homebrew python may need: brew install python-tk"),
    "windows": "Re-run the python.org installer and tick "
               "'tcl/tk and IDLE'.",
}


class Check:
    def __init__(self):
        self.lines = []
        self.fatal = False       # nothing will run
        self.gui_broken = False  # command line fine, GUIs not

    def ok(self, label, detail=""):
        self.lines.append(("ok", label, detail))

    def warn(self, label, detail=""):
        self.lines.append(("warn", label, detail))

    def fail(self, label, detail="", fatal=True):
        self.lines.append(("fail", label, detail))
        if fatal:
            self.fatal = True


def check_python(c):
    v = sys.version_info
    shown = f"{v.major}.{v.minor}.{v.micro}"
    if (v.major, v.minor) >= MIN_PYTHON:
        c.ok(f"Python {shown}", f"{platform.python_implementation()} on "
                                f"{platform.system()} {platform.machine()}")
    else:
        need = ".".join(str(x) for x in MIN_PYTHON)
        c.fail(f"Python {shown} is too old",
               f"This toolkit needs {need} or newer. Install a current "
               f"Python from python.org and run it with that.")


def check_stdlib(c):
    missing = []
    for mod in STDLIB:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        c.fail("Standard library modules missing: " + ", ".join(missing),
               "This usually means a cut-down or embedded Python. Use a "
               "normal python.org or distribution build.")
    else:
        c.ok(f"Standard library complete ({len(STDLIB)} modules)",
             "no third-party packages are needed")


def check_tkinter(c):
    try:
        import tkinter
    except ImportError:
        system = platform.system().lower()
        key = ("windows" if "windows" in system
               else "darwin" if "darwin" in system else "linux")
        c.fail("tkinter is not available",
               "The command-line tools will work; the viewer and editor "
               "will not.\n  " + TK_HELP[key], fatal=False)
        c.gui_broken = True
        return
    try:
        version = str(tkinter.TkVersion)
    except Exception:
        version = "?"
    c.ok(f"tkinter present (Tk {version})", "the GUI programs can run")


def check_files(c, folder):
    missing = [(f, why) for f, why in TOOLKIT_FILES
               if not os.path.exists(os.path.join(folder, f))]
    if not missing:
        c.ok(f"All {len(TOOLKIT_FILES)} toolkit files present", folder)
        return
    detail = "\n".join(f"    {f:<20} {why}" for f, why in missing)
    c.fail(f"{len(missing)} toolkit file(s) missing from {folder}",
           detail + "\n  Every .py file has to sit in the same folder.\n"
                    "  Do not rename them: h3m_render.py (drawing code) and\n"
                    "  h3m_viewer.py (the read-only program) are different "
                    "files.")


def check_imports(c, folder):
    """Import the library modules for real, to catch a corrupted copy."""
    if folder not in sys.path:
        sys.path.insert(0, folder)
    broken = []
    for mod in ("h3m", "h3m_render", "h3m_creatures", "h3m_balance",
                "h3m_army", "h3m_report"):
        try:
            importlib.import_module(mod)
        except Exception as exc:
            broken.append(f"{mod}: {exc}")
    if broken:
        c.fail("Some toolkit modules failed to import",
               "\n".join("    " + b for b in broken)
               + "\n  A file is probably truncated or edited. Re-copy it.")
    else:
        c.ok("Toolkit modules import cleanly",
             "parser, renderer, balance model, reports")


def check_data(c):
    """Confirm the reference tables are intact, since they are the one thing
    that would silently degrade results rather than raise an error."""
    try:
        import h3m_creatures as creatures
    except Exception:
        return
    n_creatures = len(getattr(creatures, "CREATURE_DATA", {}))
    n_artifacts = len(getattr(creatures, "ARTIFACT_CLASS", {}))
    if n_creatures >= 140 and n_artifacts >= 140:
        c.ok(f"Reference data loaded",
             f"{n_creatures} creatures, {n_artifacts} artifact classes")
    else:
        c.warn("Reference data looks incomplete",
               f"{n_creatures} creatures and {n_artifacts} artifacts loaded; "
               f"expected about 146 and 141. Balance results may be off.")


def report(c, quiet):
    if quiet:
        return
    mark = {"ok": "  OK  ", "warn": " WARN ", "fail": " FAIL "}
    print()
    print("HoMM3 Map Toolkit — environment check")
    print("=" * 62)
    for kind, label, detail in c.lines:
        print(f"[{mark[kind]}] {label}")
        if detail:
            for line in detail.split("\n"):
                print(f"          {line}")
    print("=" * 62)
    if c.fatal:
        print("Not ready. Fix the items marked FAIL above.")
    elif c.gui_broken:
        print("Command-line tools are ready. Install tkinter for the GUIs:")
        print("    python3 h3m.py MAP.h3m            # works now")
        print("    python3 h3m_viewer.py MAP.h3m     # needs tkinter")
    else:
        print("Everything is ready.")
        print()
        print("    python3 h3m_viewer.py MAP.h3m     # inspect a map")
        print("    python3 h3m_editor.py MAP.h3m     # edit a map")
        print("    python3 h3m.py MAP.h3m            # command-line summary")
    print()


def main():
    ap = argparse.ArgumentParser(
        description="Check that this machine can run the HoMM3 map toolkit. "
                    "Installs nothing.")
    ap.add_argument("--quiet", action="store_true",
                    help="print nothing; use the exit status")
    ap.add_argument("--folder", default=None,
                    help="where the toolkit files are (default: next to this "
                         "script)")
    args = ap.parse_args()

    folder = args.folder or os.path.dirname(os.path.abspath(__file__)) or "."

    c = Check()
    check_python(c)
    check_stdlib(c)
    check_tkinter(c)
    check_files(c, folder)
    if not c.fatal:
        check_imports(c, folder)
        check_data(c)
    report(c, args.quiet)

    if c.fatal:
        return 2
    if c.gui_broken:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

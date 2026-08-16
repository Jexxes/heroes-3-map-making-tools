#!/usr/bin/env python3
"""
h3m_viewer.py — read-only map analysis.

Opens a .h3m, draws it, and tells you what is on any tile you hover. It can
run every export and the balance analysis, but it cannot change a map, so
there is no way to damage a file you are only inspecting.

    python3 h3m_viewer.py            # then File > Open
    python3 h3m_viewer.py MyMap.h3m

Use h3m_editor.py when you want to make changes.
"""

import sys

REQUIRED = ["h3m.py", "h3m_render.py", "h3m_gui.py", "h3m_creatures.py",
            "h3m_balance.py", "h3m_army.py", "h3m_report.py"]


def _preflight():
    """Fail with a readable message if a file is missing from the folder."""
    import os
    here = os.path.dirname(os.path.abspath(__file__)) or "."
    missing = [f for f in REQUIRED if not os.path.exists(os.path.join(here, f))]
    if missing:
        raise SystemExit(
            "These files are missing from " + here + ":\n"
            + "\n".join("  - " + m for m in missing)
            + "\n\nEvery .py file of the tool has to sit in the same folder."
              "\nCopy the missing ones in and run this again."
              "\n\nDo not rename anything: h3m_render.py (drawing code) and"
              "\nh3m_viewer.py (the read-only program) are different files.")


_preflight()

from h3m_gui import MapViewer


class Viewer(MapViewer):
    READ_ONLY = True


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    Viewer(path, read_only=True).mainloop()


if __name__ == "__main__":
    main()

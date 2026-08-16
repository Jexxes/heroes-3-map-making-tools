#!/usr/bin/env python3
"""
h3m_editor.py — map editing and balancing.

Everything the viewer does, plus editing: message text, creature stacks,
owners, object removal, auto-balance, and filling a stack to a target total.
Changes are queued and can be undone individually; nothing reaches disk until
you save.

    python3 h3m_editor.py            # then File > Open
    python3 h3m_editor.py MyMap.h3m
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


class Editor(MapViewer):
    READ_ONLY = False


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    Editor(path, read_only=False).mainloop()


if __name__ == "__main__":
    main()

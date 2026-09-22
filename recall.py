#!/usr/bin/env python3
"""Fetch an archived tool result by tool_use_id.

  recall.py <id>                    full text
  recall.py <id> --grep PATTERN     only lines matching a regex (case-insensitive)
  recall.py <id> --range A B        chars A..B
  recall.py --list [N]              last N archived results (default 20)
  recall.py --session <session_id>  results of one session
"""
import os
import re
import sqlite3
import sys

DB_PATH = os.path.expanduser("~/.claude/tool-logs/tool_log.sqlite")


def con():
    return sqlite3.connect(DB_PATH)


def show_list(rows):
    for r in rows:
        print(f"{r[0]}  {r[2]:<40} {r[3]:>9,} chars  {r[1]}")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    c = con()
    if argv[0] == "--list":
        n = int(argv[1]) if len(argv) > 1 else 20
        rows = c.execute(
            "SELECT id, datetime(ts,'unixepoch','localtime'), tool_name, size_chars FROM results ORDER BY ts DESC LIMIT ?", (n,)
        ).fetchall()
        show_list(rows)
        return
    if argv[0] == "--session":
        rows = c.execute(
            "SELECT id, datetime(ts,'unixepoch','localtime'), tool_name, size_chars FROM results WHERE session_id=? ORDER BY ts", (argv[1],)
        ).fetchall()
        show_list(rows)
        return

    tool_use_id = argv[0]
    row = c.execute("SELECT output, tool_name, tool_input FROM results WHERE id=?", (tool_use_id,)).fetchone()
    if row is None:
        # allow prefix match on the id
        row = c.execute("SELECT output, tool_name, tool_input FROM results WHERE id LIKE ?", (tool_use_id + "%",)).fetchone()
    if row is None:
        print(f"no archived result for id {tool_use_id}", file=sys.stderr)
        sys.exit(1)
    text, tool_name, tool_input = row

    if len(argv) >= 3 and argv[1] == "--grep":
        pat = re.compile(argv[2], re.I)
        for i, line in enumerate(text.splitlines(), 1):
            if pat.search(line):
                print(f"{i}: {line}")
        return
    if len(argv) >= 4 and argv[1] == "--range":
        print(text[int(argv[2]):int(argv[3])])
        return
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])

#!/usr/bin/env python3
"""Serve a child workflow's entry point (a route-only `script` node; stdout JSON -> outputs).

A subworkflow always starts at its `start` node. A child that a parent may enter at more than
one place (a scoped revision skipping straight to its later half) starts with a script node
running this helper, and that node's `routes:` branch on the child's own inputs. The helper
does no work and never fails: it echoes the routing value so the ledger records which entry
was taken.

    python3 entry_serve.py <value>   ->   {"entry": "<value>"}
"""

import json
import sys


def main(argv):
    print(json.dumps({"entry": argv[1] if len(argv) > 1 else ""}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

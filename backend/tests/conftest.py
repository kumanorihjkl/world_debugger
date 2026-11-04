"""Isolate the rule store for tests: point RULES_FILE at a tmp file.

Imported before test modules import the app, so routes load from scratch.
"""

import os
import tempfile

_tmp = os.path.join(tempfile.mkdtemp(prefix="wd-test-rules-"), "rules.json")
os.environ["RULES_FILE"] = _tmp

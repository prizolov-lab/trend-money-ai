import os
import sqlite3
import tempfile
import unittest

os.environ["AGENOMICS_EVIDENCE"] = "1"
try:
    import agenomics  # noqa: F401
except ImportError:
    agenomics = None

import agenomics_hook as h


@unittest.skipIf(agenomics is None, "agenomics не установлен")
class HookTest(unittest.TestCase):
    def test_flow(self):
        db = tempfile.mkdtemp() + "/e.db"
        k = h.Hook(db)
        t = k.start()
        k.finish(t, True)
        k.human(t[0], False)
        k.human(t[0], True)  # повтор игнорируется
        rows = sqlite3.connect(db).execute(
            "select outcome_type, occurred, quality_level from outcomes order by id"
        ).fetchall()
        self.assertEqual(rows, [("execution_error", 1, "Q1"), ("task_failure", 1, "Q4")])

    def test_text_not_stored(self):
        db = tempfile.mkdtemp() + "/e.db"
        k = h.Hook(db)
        k.finish(k.start(), False)
        dump = "\n".join(sqlite3.connect(db).iterdump())
        self.assertNotIn("Дай 5", dump)


if __name__ == "__main__":
    unittest.main()

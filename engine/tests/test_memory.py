import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import memory  # noqa: E402


class MemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="maestro-mem-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def kdir(self):
        d = os.path.join(self.tmp, ".maestro", "memory", "knowledge")
        os.makedirs(d, exist_ok=True)
        return d

    def test_read_knowledge_empty_when_absent(self):
        self.assertEqual(memory.read_knowledge(self.tmp), {})

    def test_read_knowledge_reads_only_md(self):
        d = self.kdir()
        open(os.path.join(d, "codebase.md"), "w").write("line1\nline2\n")
        open(os.path.join(d, "plan.md"), "w").write("plan lesson")
        open(os.path.join(d, "ignore.txt"), "w").write("nope")
        k = memory.read_knowledge(self.tmp)
        self.assertEqual(set(k), {"codebase", "plan"})
        self.assertEqual(k["codebase"], "line1\nline2\n")

    def test_snapshot_roundtrip_multiline(self):
        data = {"codebase": "multi\nline\n# md **bold** ${notaref}\n", "plan": "x"}
        memory.write_snapshot("feat", self.tmp, data)
        self.assertEqual(memory.load_snapshot("feat", self.tmp), data)

    def test_load_snapshot_empty_when_absent(self):
        self.assertEqual(memory.load_snapshot("nope", self.tmp), {})


if __name__ == "__main__":
    unittest.main()

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import mem_consolidate  # noqa: E402


class ConsolidateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mem-cons-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.mem = os.path.join(self.tmp, ".maestro", "memory")
        os.makedirs(os.path.join(self.mem, "incoming"))

    def drop(self, slug, lessons):
        with open(os.path.join(self.mem, "incoming", slug + ".json"), "w") as fh:
            json.dump({"slug": slug, "lessons": lessons}, fh)

    def knowledge(self, domain):
        p = os.path.join(self.mem, "knowledge", domain + ".md")
        return open(p).read() if os.path.exists(p) else ""

    def L(self, text="N+1 in list endpoints", domain="backend-review", key="n-plus-one", **kw):
        return {"domain": domain, "key": key, "text": text, **kw}

    def test_single_run_stays_candidate(self):
        self.drop("run1", [self.L()])
        r = mem_consolidate.consolidate(self.mem, threshold=3)
        self.assertEqual(r["promoted"], 0)
        self.assertEqual(self.knowledge("backend-review"), "")  # not injected

    def test_three_distinct_runs_promote(self):
        for slug in ("run1", "run2", "run3"):
            self.drop(slug, [self.L()])
            mem_consolidate.consolidate(self.mem, threshold=3)
        self.assertIn("N+1 in list endpoints", self.knowledge("backend-review"))
        self.assertIn("seen: 3", self.knowledge("backend-review"))

    def test_same_slug_repeated_counts_once(self):
        for _ in range(3):
            self.drop("run1", [self.L()])  # same slug re-observed
            mem_consolidate.consolidate(self.mem, threshold=3)
        self.assertEqual(self.knowledge("backend-review"), "")  # only 1 distinct slug

    def test_authoritative_promotes_immediately(self):
        self.drop("bootstrap", [self.L(text="Use Postgres 16", domain="codebase",
                                       key="pg16", authoritative=True)])
        mem_consolidate.consolidate(self.mem, threshold=3)
        self.assertIn("Use Postgres 16", self.knowledge("codebase"))
        self.assertIn("authoritative", self.knowledge("codebase"))

    def test_incoming_cleared_after_fold(self):
        self.drop("run1", [self.L()])
        mem_consolidate.consolidate(self.mem, threshold=3)
        self.assertEqual(os.listdir(os.path.join(self.mem, "incoming")), [])

    def test_invalid_incoming_skipped(self):
        with open(os.path.join(self.mem, "incoming", "junk.json"), "w") as fh:
            fh.write("artifact\n")  # not valid JSON — e.g. an e2e touch-stub
        r = mem_consolidate.consolidate(self.mem, threshold=3)
        self.assertEqual(r["promoted"], 0)

    def test_threshold_override(self):
        for slug in ("run1", "run2"):
            self.drop(slug, [self.L()])
            mem_consolidate.consolidate(self.mem, threshold=2)
        self.assertIn("seen: 2", self.knowledge("backend-review"))  # promotes at 2

    def test_unsafe_domains_are_skipped_not_written_or_crashing(self):
        outside = os.path.join(self.tmp, ".maestro")  # '../..' from candidates/ lands here
        self.drop("run1", [self.L(domain="../.."), self.L(domain="api/payments"),
                           self.L(domain=".."), self.L(domain=".hidden"), self.L(domain=3),
                           self.L(domain="ok-domain", key="k")])
        r = mem_consolidate.consolidate(self.mem, threshold=1)
        self.assertEqual(r["domains"], 1)
        self.assertEqual(sorted(os.listdir(os.path.join(self.mem, "candidates"))),
                         ["ok-domain.json"])
        self.assertFalse(os.path.exists(os.path.join(outside, "candidates")))
        self.assertFalse(os.path.exists(os.path.join(self.mem, "candidates", "api")))
        self.assertEqual(os.listdir(os.path.join(self.mem, "incoming")), [])
        # the harvest keeps working afterwards
        self.drop("run2", [self.L(domain="ok-domain", key="k")])
        self.assertEqual(mem_consolidate.consolidate(self.mem, threshold=2)["promoted"], 1)

    def test_a_bad_ledger_file_from_an_earlier_run_does_not_crash_later_harvests(self):
        cand = os.path.join(self.mem, "candidates")
        os.makedirs(cand)
        with open(os.path.join(cand, "..json"), "w") as fh:  # domain "."
            json.dump([{"key": "a", "text": "x", "slugs": ["r"]}], fh)
        with open(os.path.join(cand, "good.json"), "w") as fh:
            json.dump([{"key": ["unhashable"], "text": "x"},
                       {"key": "k", "text": "t", "slugs": [["bad"], "r1"]}], fh)
        self.drop("run1", [self.L()])
        r = mem_consolidate.consolidate(self.mem, threshold=1)
        self.assertEqual(r["domains"], 2)
        self.assertIn("N+1", self.knowledge("backend-review"))


if __name__ == "__main__":
    unittest.main()

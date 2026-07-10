"""Unit tests for the strict-subset YAML loader/emitter."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import wf  # noqa: E402


class LoadTest(unittest.TestCase):
    def test_scalars(self):
        doc = wf.loads("a: 1\nb: -2\nc: 1.5\nd: true\ne: false\nf: null\ng: ~\nh: hello\n")
        self.assertEqual(doc, {"a": 1, "b": -2, "c": 1.5, "d": True, "e": False,
                               "f": None, "g": None, "h": "hello"})

    def test_quoted_strings(self):
        doc = wf.loads('a: "true"\nb: \'123\'\nc: "with # hash"\nd: "esc\\"q"\ne: \'it\'\'s\'\n')
        self.assertEqual(doc, {"a": "true", "b": "123", "c": "with # hash",
                               "d": 'esc"q', "e": "it's"})

    def test_comments(self):
        doc = wf.loads("# full line\na: 1  # trailing\nb: \"x # not a comment\"\n")
        self.assertEqual(doc, {"a": 1, "b": "x # not a comment"})

    def test_nested_maps_and_lists(self):
        doc = wf.loads(
            "top:\n  inner:\n    - x\n    - y: 2\n      z: 3\n  other: v\n"
        )
        self.assertEqual(doc, {"top": {"inner": ["x", {"y": 2, "z": 3}], "other": "v"}})

    def test_same_indent_list_under_key(self):
        doc = wf.loads("run:\n- bash\n- -c\n- echo hi\nnext: end\n")
        self.assertEqual(doc, {"run": ["bash", "-c", "echo hi"], "next": "end"})

    def test_flow_collections(self):
        doc = wf.loads('a: [1, two, "th ree"]\nb: {x: 1, y: [2, 3], z: {q: true}}\nc: []\nd: {}\n')
        self.assertEqual(doc, {"a": [1, "two", "th ree"],
                               "b": {"x": 1, "y": [2, 3], "z": {"q": True}},
                               "c": [], "d": {}})

    def test_block_literal(self):
        doc = wf.loads("a: |\n  line1\n  line2\n\n  after blank\nb: 1\n")
        self.assertEqual(doc["a"], "line1\nline2\n\nafter blank\n")
        self.assertEqual(doc["b"], 1)

    def test_block_literal_strip(self):
        doc = wf.loads("a: |-\n  only\nb: 2\n")
        self.assertEqual(doc["a"], "only")
        self.assertEqual(doc["b"], 2)

    def test_block_literal_keeps_hashes_and_colons(self):
        doc = wf.loads("a: |\n  # not a comment\n  key: value inside\n")
        self.assertEqual(doc["a"], "# not a comment\nkey: value inside\n")

    def test_placeholders_survive(self):
        doc = wf.loads('a: "${inputs.slug}"\nb: ${steps.x.outputs.y}\n')
        self.assertEqual(doc["a"], "${inputs.slug}")
        self.assertEqual(doc["b"], "${steps.x.outputs.y}")

    def test_list_of_compact_maps(self):
        doc = wf.loads("routes:\n  - {when: \"${x} == 1\", to: a}\n  - {to: b}\n")
        self.assertEqual(doc["routes"], [{"when": "${x} == 1", "to": "a"}, {"to": "b"}])

    def test_empty_document(self):
        self.assertEqual(wf.loads(""), {})
        self.assertEqual(wf.loads("# just a comment\n"), {})

    def test_rejects_unsupported(self):
        for bad in ("a: &anchor 1", "a: *ref", "a: !!str x", "a: >\n  folded",
                    "a: 1\n---\nb: 2", "\ta: 1", "a: 1\na: 2"):
            with self.assertRaises(wf.WfError, msg=bad):
                wf.loads(bad)

    def test_rejects_bad_indent(self):
        with self.assertRaises(wf.WfError):
            wf.loads("a: 1\n   b: 2\n")

    def test_rejects_unterminated_flow(self):
        with self.assertRaises(wf.WfError):
            wf.loads("a: [1, 2\n")


class DumpTest(unittest.TestCase):
    def rt(self, obj):
        text = wf.dumps(obj)
        back = wf.loads(text)
        self.assertEqual(back, obj, f"round-trip failed for {obj!r}:\n{text}")
        self.assertEqual(wf.dumps(back), text, "dump not stable")
        return text

    def test_roundtrip_scalars(self):
        self.rt({"a": 1, "b": True, "c": None, "d": "plain", "e": "needs: quote",
                 "f": "123", "g": "true", "h": "", "i": -1.25})

    def test_roundtrip_structures(self):
        self.rt({
            "nodes": [
                {"id": "x", "run": ["bash", "-c", "echo '{\"a\": 1}'"],
                 "routes": [{"when": "${steps.x.outputs.s} == ask", "to": "y"}, {"to": "end"}]},
                {"id": "y", "prompt": "line1\nline2\n", "options": [
                    {"id": "ok", "label": "OK — proceed", "to": "end"}]},
            ],
            "empty_list": [], "empty_map": {},
        })

    def test_roundtrip_multiline_no_trailing_newline(self):
        self.rt({"a": "x\ny"})

    def test_roundtrip_state_like(self):
        self.rt({
            "steps": {
                "design/author_hld": {"status": "done", "visits": 2,
                                      "outputs": {"summary": "It's a plan: 100% done"}},
                "work[be]/impl": {"status": "pending", "attempts": 0, "visits": 1, "outputs": {}},
            },
            "gates": [{"step": "a", "option": "revise", "input": "make it: better", "at": "t"}],
        })


class QuoteScanTest(unittest.TestCase):
    def test_quoted_scalar_with_escapes_and_colon_is_not_a_key(self):
        doc = wf.loads("run:\n  - 'echo ''stub: here''; exit 0'\nx: 'a''b: c''d'\n'quoted key': v\n")
        self.assertEqual(doc["run"], ["echo 'stub: here'; exit 0"])
        self.assertEqual(doc["x"], "a'b: c'd")
        self.assertEqual(doc["quoted key"], "v")


if __name__ == "__main__":
    unittest.main()

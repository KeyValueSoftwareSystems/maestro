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


class RoundTripHardStringsTest(unittest.TestCase):
    """Strings the engine actually writes into state.yaml (agent outputs, gate input,
    failure reasons) must survive dump->load. These once silently corrupted a run."""

    def rt(self, obj):
        back = wf.loads(wf.dumps(obj))
        self.assertEqual(back, obj, f"round-trip failed:\n{wf.dumps(obj)}")

    def test_markdown_rule_inside_value(self):
        self.rt({"steps": {"x": {"outputs": {"summary": "Done.\n---\nNotes: extra"}}}})

    def test_markdown_rule_in_instruction_literal(self):
        # an indented `---` in a block literal is not a document separator
        doc = wf.loads('i: |\n  Section A\n  ---\n  Section B\n')
        self.assertEqual(doc["i"], "Section A\n---\nSection B\n")

    def test_carriage_return(self):
        self.rt({"a": "line1\rline2"})
        self.rt({"a": "windows\r\nnewlines\r\n"})

    def test_leading_space_first_line(self):
        self.rt({"i": "  indented first\nflush second"})

    def test_whitespace_only_interior_line(self):
        self.rt({"i": "a\n  \nb"})

    def test_tabs_and_quotes(self):
        self.rt({"i": "col1\tcol2\nrow2", "j": 'said "hi"\nbye'})

    def test_leading_doc_sep_allowed_multidoc_rejected(self):
        self.assertEqual(wf.loads("---\na: 1\n"), {"a": 1})
        with self.assertRaises(wf.WfError):
            wf.loads("a: 1\n---\nb: 2\n")


class LedgerCorruptionTest(unittest.TestCase):
    """Agent text that once saved fine and then broke every later load of the run."""

    def rt(self, obj):
        text = wf.dumps(obj)
        self.assertEqual(wf.loads(text), obj, f"round-trip failed:\n{text}")
        self.assertEqual(wf.dumps(wf.loads(text)), text, "dump not stable")

    def test_brace_in_flow_value_does_not_merge_fields(self):
        obj = {"f": {"summary": "added missing } in parser", "blocking": True}}
        self.rt(obj)
        self.assertIs(wf.loads(wf.dumps(obj))["f"]["blocking"], True)
        self.rt({"f": ["a { b", "c } d", "{", "}", "x}y{z"]})
        self.rt({"f": {"k}": 1, "a{b": 2}})

    def test_placeholders_stay_plain_in_flow(self):
        text = wf.dumps({"r": {"when": "a ${steps.x.outputs.y} b", "to": "z"}})
        self.assertIn("when: a ${steps.x.outputs.y} b", text)
        self.rt({"r": {"when": "a ${steps.x.outputs.y} b", "to": "z"}})

    def test_flow_quoted_escapes_do_not_split(self):
        self.assertEqual(wf.loads('a: ["say \\"hi\\", ok", b]\n'), {"a": ['say "hi", ok', "b"]})
        self.assertEqual(wf.loads("a: ['it''s, ok', b]\n"), {"a": ["it's, ok", "b"]})
        self.rt({"a": ['say "hi", ok', "b\\", "c"]})

    def test_line_separators_round_trip(self):
        for ch in "\u2028\u2029\x85\x0b\x0c\x1c\x1d\x1e\x00\x7f\ufeff\r":
            self.rt({"a": f"x{ch}y", "b": [f"p{ch}", {"k": f"{ch}q\nr"}], f"k{ch}": 1})
        # raw separators written by another tool must not cut a quoted scalar
        self.assertEqual(wf.loads('a: "x\u2028y"\nb: 1\n'), {"a": "x\u2028y", "b": 1})

    def test_escapes_decode(self):
        self.assertEqual(wf.loads('a: "\\x0b\\u2028\\U0001f600 \\\\x41 C:\\\\dir \\q"\n'),
                         {"a": "\x0b\u2028\U0001f600 \\x41 C:\\dir \\q"})

    def test_tab_leading_line_in_multiline_value(self):
        self.rt({"a": "func f() {\n\treturn 1\n}\n", "b": "x\n\ty"})
        doc = wf.loads("a: |\n  func f() {\n  \treturn 1\n  }\nb: 1\n")
        self.assertEqual(doc, {"a": "func f() {\n\treturn 1\n}\n", "b": 1})

    def test_tab_in_structural_indentation_still_rejected(self):
        for bad in ("a:\n\tb: 1\n", "a: |\n  x\nb:\n\tc: 1\n", "\ta: 1"):
            with self.assertRaises(wf.WfError, msg=bad):
                wf.loads(bad)

    def test_trailing_newlines_and_blank_values(self):
        for v in ("a\n\n", "a\n\n\n", "\n", "\n\n", "\nfoo", "\n\nfoo\n", "  \n", "a\n \n"):
            self.rt({"a": v, "z": 1})

    def test_nested_lists(self):
        self.rt({"a": [[1, [2, 3]], [[]], [{"k": "v"}], ["x\ny"], [[1] * 60]]})

    def test_float_exponent_round_trips(self):
        self.rt({"a": 1e-05, "b": 1e20, "c": 0.5})


class BlockLiteralHeaderTest(unittest.TestCase):
    def test_chomping_indicators(self):
        doc = wf.loads("a: |\n  x\n\nb: |-\n  y\n\nc: |+\n  z\n\nd: |+\n  w\n")
        self.assertEqual(doc, {"a": "x\n", "b": "y", "c": "z\n\n", "d": "w\n"})

    def test_keep_at_end_of_file_and_empty(self):
        self.assertEqual(wf.loads("a: |+\n  x\n\n\n"), {"a": "x\n\n\n"})
        self.assertEqual(wf.loads("a: |+\n\nb: 1\n"), {"a": "\n", "b": 1})
        self.assertEqual(wf.loads("a: |\nb: 1\n"), {"a": "", "b": 1})

    def test_indentation_indicator_either_order(self):
        for hdr, want in (("|2", " z\n"), ("|2-", " z"), ("|-2", " z"), ("|+2", " z\n"), ("|2+", " z\n")):
            self.assertEqual(wf.loads(f"a: {hdr}\n   z\nb: 1\n"), {"a": want, "b": 1}, hdr)

    def test_indentation_indicator_keeps_leading_spaces_and_blank_space(self):
        doc = wf.loads("a: |2\n    code\n\n     more\n  \n  end\nb: 1\n")
        self.assertEqual(doc, {"a": "  code\n\n   more\n\nend\n", "b": 1})

    def test_header_in_list_item_map_and_comment(self):
        doc = wf.loads("l:\n  - k: |+  # keep\n      x\n\n    n: |2-\n        y\n")
        self.assertEqual(doc, {"l": [{"k": "x\n\n", "n": "  y"}]})

    def test_folded_with_indicators_still_rejected(self):
        for hdr in (">", ">-", ">+", ">2", ">2-"):
            with self.assertRaises(wf.WfError, msg=hdr):
                wf.loads(f"a: {hdr}\n  x\n")


class PropertyRoundTripTest(unittest.TestCase):
    """dump->load must be an identity for arbitrary strings the ledger may carry."""

    ATOMS = ["{", "}", "[", "]", ":", ": ", "#", " #", "'", '"', "\\", "\n", "\r", "\t", " ", "  ",
             "\u2028", "\u2029", "\x85", "\x0b", "\x1c", "\x00", "\x7f", "\ufeff", "\xe9", "a", "b",
             "true", "null", "1", "1.5", "-", "- ", "? ", "|", ">", "---", "${x}", "${", ",", "\xa0",
             "\U0001f600", "~", "&", "*", "!", "%", "@", "`", "1e5", "0x1"]
    FIXED = ["", " ", "  x", "x  ", "{", "}", "{}", "[]", "[a, b]", "{a: b}", "a}b", "a{b", ":", "a:", ": a",
             "a: b", "#c", "a #c", "'", '"', "\\", "\\n", "true", "False", "null", "~", "Null", "1", "-1",
             "1.5", "0123", "1e5", "- a", "-", "? a", "|", "|-", ">", "&a", "*a", "!a", "%a", "@a",
             "`a", "---", "a\n---\nb", "\n", "a\n", "a\n\n", "\ta", "a\n\tb", "\u2028", "a\u2029b",
             "${steps.x.outputs.y}", "x ${a} }", "\x85", "\x0b\x0c\x1c\x1d\x1e"]

    def values(self):
        import random

        rnd = random.Random(20240601)
        out = list(self.FIXED)
        for _ in range(400):
            out.append("".join(rnd.choice(self.ATOMS) for _ in range(rnd.randint(1, 7))))
        return out

    def check(self, obj):
        text = wf.dumps(obj)
        try:
            back = wf.loads(text)
        except wf.WfError as e:
            self.fail(f"load failed ({e}) for {obj!r}:\n{text}")
        self.assertEqual(back, obj, f"round-trip failed:\n{text}")

    def test_strings_in_every_position(self):
        vals = self.values()
        for v in vals:
            with self.subTest(v=v):
                self.check({"k": v})
                self.check({"k": [v]})
                self.check({"k": {"x": v, "y": 1}})
                self.check({"k": [{"a": v}, [v, 2]], "z": {"n": {"m": v}}})
                self.check({v or "empty": 1, "x": {v or "empty": [v]}})
        self.check({f"k{i}": v for i, v in enumerate(vals)})
        self.check({"all": vals, "flow": {"a": vals[:3]}})

    def test_non_string_scalars_next_to_strings(self):
        self.check({"a": [None, True, False, 0, -7, 2.5, 1e-07, "1", "true", "null", ""],
                    "b": {"c": None, "d": [None], "e": {}}, "f": [[], {}]})


if __name__ == "__main__":
    unittest.main()

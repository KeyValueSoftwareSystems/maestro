"""render_doc.py — deterministic Markdown -> self-contained HTML for stage artifacts.

Proves the render is: complete over the SDLC Markdown subset, self-contained (no external
assets), publish-ready (no <html>/<head>/<body> wrapper), and byte-deterministic so it is
golden-set testable like the rest of the engine.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import render_doc  # noqa: E402


SAMPLE = """# HLD — Auth feature

Some **bold** and *italic* and `inline code` and a [link](https://example.com).

## Decision summary

- opaque token
- bcrypt hashing

1. backend
2. react
3. flutter

| Decision | Reason |
| --- | --- |
| Bearer token | one mechanism |
| SQLite | zero infra |

> A quote about sessions.

```
GET /me
Authorization: Bearer <token>
```

---

Done.
"""


class RenderDocTest(unittest.TestCase):
    def setUp(self):
        self.html = render_doc.render(SAMPLE)

    def test_covers_the_markdown_subset(self):
        h = self.html
        self.assertIn("<h1>HLD — Auth feature</h1>", h)
        self.assertIn("<h2>Decision summary</h2>", h)
        self.assertIn("<strong>bold</strong>", h)
        self.assertIn("<em>italic</em>", h)
        self.assertIn("<code>inline code</code>", h)
        self.assertIn('<a href="https://example.com">link</a>', h)
        self.assertIn("<ul>", h)
        self.assertIn("<ol>", h)
        self.assertIn("<table>", h)
        self.assertIn("<th>Decision</th>", h)
        self.assertIn("<td>Bearer token</td>", h)
        self.assertIn("<blockquote>", h)
        self.assertIn("<pre><code>", h)
        self.assertIn("<hr>", h)

    def test_code_block_is_escaped_not_interpreted(self):
        # angle brackets inside a fence must be escaped, never emitted as tags
        self.assertIn("Bearer &lt;token&gt;", self.html)

    def test_self_contained_and_publish_ready(self):
        h = self.html
        # no document wrapper — the artifact publisher supplies it, and browsers
        # still render a bare <style> + content fragment locally.
        self.assertNotIn("<!doctype", h.lower())
        self.assertNotIn("<html", h.lower())
        self.assertNotIn("<body", h.lower())
        # no external assets (only the in-content link, which is content not an asset ref)
        self.assertNotIn("http-equiv", h.lower())
        self.assertNotIn("<script", h.lower())
        self.assertNotIn("<link", h.lower())
        self.assertIn("<style>", h)

    def test_title_from_first_h1_or_override(self):
        self.assertIn("Stage artifact · HLD — Auth feature", self.html)
        self.assertIn(
            "Stage artifact · Custom", render_doc.render("no heading here", title="Custom")
        )

    def test_deterministic(self):
        self.assertEqual(self.html, render_doc.render(SAMPLE))

    def test_cli_writes_sibling_html(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "hld.md")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(SAMPLE)
            rc = render_doc.main([src])
            self.assertEqual(rc, 0)
            out = os.path.join(d, "hld.html")
            self.assertTrue(os.path.exists(out))
            with open(out, encoding="utf-8") as fh:
                self.assertIn("<h1>HLD — Auth feature</h1>", fh.read())


if __name__ == "__main__":
    unittest.main()

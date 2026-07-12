# Third-party components

Maestro ships one vendored third-party component. Everything else in this repo is
original and stdlib-only (the engine has zero runtime dependencies).

## js-yaml 4.1.0

- **Where:** inlined in `ui/builder.html` (the single-file visual workflow builder), so
  the builder works offline with no CDN or build step.
- **Upstream:** https://github.com/nodeca/js-yaml
- **License:** MIT

```
Copyright (C) 2011-2015 by Vitaly Puzrin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## Superpowers skills (optional, not vendored)

`install.sh` can install six helper skills from the [Superpowers](https://github.com/obra/superpowers)
pack (`brainstorming`, `writing-plans`, `test-driven-development`, `requesting-code-review`,
`systematic-debugging`, `using-git-worktrees`) via `npx skills add`. They are fetched at
install time from their own upstream and are governed by that project's license — nothing
from it is copied into this repository.

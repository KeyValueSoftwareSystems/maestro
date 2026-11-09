# Attributions

This pack's **core engine, workflows, and SDLC step skills** are original to
KeyValue Software Systems (see `LICENSE`, MIT).

## Per-stack skills — imported from ECC

The per-stack reference skills (`skills/<lang>-patterns`, `-testing`, framework guides) and the
per-stack review checklists (`<lang>-review`) are adapted from **ECC** —
<https://github.com/affaan-m/ECC>, MIT License, Copyright (c) 2026 Affaan Mustafa. For the
reference skills only the frontmatter was normalised to this pack's contract (added `tags:` with
a `stack:<x>` token and `allowed-tools`); the instructional bodies are ECC's. Each review
checklist is the checklist part of an ECC reviewer agent (`agents/<lang>-reviewer`), kept as a
skill without the agent's persona, procedure and verdict sections. These files carry no
in-file attribution — this file plus `licenses/ECC-LICENSE` are the record of origin.

The MIT license requires this notice be preserved. See `licenses/ECC-LICENSE` for the
full upstream license text.

### Imported, by stack

| Stack | Skills | Review checklist (from the ECC agent) |
| --- | --- | --- |
| **android** | `android-clean-architecture`, `compose-multiplatform-patterns` | — |
| **angular** | `angular-developer` | — |
| **db** | `clickhouse-io`, `database-migrations`, `mysql-patterns`, `postgres-patterns`, `prisma-patterns`, `redis-patterns` | `database-review` (`database-reviewer`) |
| **django** | `django-celery`, `django-patterns`, `django-security`, `django-tdd`, `django-verification` | `django-review` (`django-reviewer`) |
| **fastapi** | `fastapi-patterns` | `fastapi-review` (`fastapi-reviewer`) |
| **flutter** | `dart-flutter-patterns`, `flutter-dart-code-review` | `flutter-review` (`flutter-reviewer`) |
| **go** | `golang-patterns`, `golang-testing` | `go-review` (`go-reviewer`) |
| **java** | `java-coding-standards`, `jpa-patterns`, `quarkus-patterns`, `quarkus-security`, `quarkus-tdd`, `quarkus-verification`, `springboot-patterns`, `springboot-security`, `springboot-tdd`, `springboot-verification` | `java-review` (`java-reviewer`) |
| **kotlin** | `kotlin-coroutines-flows`, `kotlin-exposed-patterns`, `kotlin-ktor-patterns`, `kotlin-patterns`, `kotlin-testing` | `kotlin-review` (`kotlin-reviewer`) |
| **node** | `nestjs-patterns`, `vite-patterns` | `typescript-review` (`typescript-reviewer`), `type-design-review` (`type-design-analyzer`) |
| **python** | `python-patterns`, `python-testing` | `python-review` (`python-reviewer`) |
| **pytorch** | `pytorch-patterns` | — |
| **react** | `nextjs-turbopack`, `react-native-patterns`, `react-patterns`, `react-performance`, `react-testing` | `react-review` (`react-reviewer`) |
| **rust** | `rust-patterns`, `rust-testing` | `rust-review` (`rust-reviewer`) |
| **vue** | `nuxt4-patterns`, `vue-patterns` | `vue-review` (`vue-reviewer`) |

_Totals: 48 reference skills and 13 review checklists across 15 stacks. Regenerate/extend via
`scripts/import_ecc.py`._

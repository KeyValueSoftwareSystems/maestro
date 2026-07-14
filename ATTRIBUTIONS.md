# Attributions

This pack's **core engine, workflows, and SDLC step skills** are original to
KeyValue Software Systems (see `LICENSE`, MIT).

## Per-stack skills & agents — imported from ECC

The per-stack reference skills (`skills/<lang>-patterns`, `-testing`, framework guides)
and per-stack reviewer subagents (`agents/<lang>-reviewer`) are adapted from **ECC** —
<https://github.com/affaan-m/ECC>, MIT License, Copyright (c) 2026 Affaan Mustafa. Only
the frontmatter was normalised to this pack's contract (added `tags:` with a `stack:<x>`
token and `allowed-tools`); the instructional bodies are ECC's. These files carry no
in-file attribution — this file plus `licenses/ECC-LICENSE` are the record of origin.

The MIT license requires this notice be preserved. See `licenses/ECC-LICENSE` for the
full upstream license text.

### Imported, by stack

| Stack | Skills | Agents |
| --- | --- | --- |
| **android** | `android-clean-architecture`, `compose-multiplatform-patterns` | — |
| **angular** | `angular-developer` | — |
| **db** | `clickhouse-io`, `database-migrations`, `mysql-patterns`, `postgres-patterns`, `prisma-patterns`, `redis-patterns` | `database-reviewer` |
| **flutter** | `dart-flutter-patterns`, `flutter-dart-code-review` | `flutter-reviewer` |
| **go** | `golang-patterns`, `golang-testing` | `go-reviewer` |
| **java** | `java-coding-standards`, `jpa-patterns`, `quarkus-patterns`, `quarkus-security`, `quarkus-tdd`, `quarkus-verification`, `springboot-patterns`, `springboot-security`, `springboot-tdd`, `springboot-verification` | `java-reviewer` |
| **kotlin** | `kotlin-coroutines-flows`, `kotlin-exposed-patterns`, `kotlin-ktor-patterns`, `kotlin-patterns`, `kotlin-testing` | `kotlin-reviewer` |
| **node** | `nestjs-patterns`, `vite-patterns` | `type-design-analyzer`, `typescript-reviewer` |
| **python** | `django-celery`, `django-patterns`, `django-security`, `django-tdd`, `django-verification`, `fastapi-patterns`, `python-patterns`, `python-testing`, `pytorch-patterns` | `django-reviewer`, `fastapi-reviewer`, `python-reviewer` |
| **react** | `nextjs-turbopack`, `react-native-patterns`, `react-patterns`, `react-performance`, `react-testing` | `react-reviewer` |
| **rust** | `rust-patterns`, `rust-testing` | `rust-reviewer` |
| **vue** | `nuxt4-patterns`, `vue-patterns` | `vue-reviewer` |

_Totals: 48 skills, 13 agents across 12 stacks. Regenerate/extend via `scripts/import_ecc.py`._

# Contributing to SafeRoute API

Thanks for your interest in SafeRoute API! We welcome issues, questions, and pull requests.

## Code of Conduct

Be respectful. No harassment, no spam, no low-effort comments. Violations → blocked.

---

## Prerequisites

| Tool       | Version  |
|------------|----------|
| Python     | 3.12+    |
| pip        | latest   |
| Git        | 2.x+     |

---

## Local Setup

```bash
# 1. Clone the repository
git clone https://github.com/darestack/saferoute-api.git
cd saferoute-api

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows

# 3. Install all dependencies (runtime + dev)
pip install -r requirements-dev.txt

# 4. Set up environment variables
cp .env.example .env
# Edit .env and add your Supabase credentials
```

---

## Running Locally

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://127.0.0.1:8000`.

---

## Running Tests

```bash
pytest tests/ -v
```

With coverage:

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

---

## Code Quality

Run these checks **before** submitting a pull request:

```bash
# Lint
ruff check app/ tests/

# Format check
ruff format --check app/ tests/

# Type check
mypy app/
```

### Style Rules

- All code must pass `ruff` linting and `mypy --strict` type checking.
- Use `from __future__ import annotations` in all new modules.
- Prefer `async`/`await` over synchronous blocking calls in async contexts.
- Use `asyncio.Lock()` instead of `threading.Lock()` in async code.
- All public functions must have docstrings with Args/Returns/Raises sections.
- Use type annotations for all function parameters and return values.
- Do not add paid dependencies or external services without discussion.

### Cleanup and Refactoring

When fixing issues or adding features:
- Remove dead code, unused imports, and redundant comments in the same PR.
- Update inline documentation to reflect new behavior.
- Add tests for any new code paths or bug fixes.
- If you change public APIs, update `__all__` declarations.

### Zero-Cost Constraint

All changes must respect the $0 total cost constraint:
- No paid tools, paid third-party services, or paid dependencies.
- No external APIs or cloud services that require payment.
- Use open-source, self-hosted, or built-in alternatives only.

---

## Commit Message Format

We follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix       | Purpose                        |
|--------------|--------------------------------|
| `feat:`      | New feature                    |
| `fix:`       | Bug fix                        |
| `docs:`      | Documentation only             |
| `chore:`     | Maintenance / tooling          |
| `test:`      | Adding or updating tests       |
| `refactor:`  | Code change (no new feature or fix) |

**Examples:**

```
feat: add retry logic for webhook delivery
fix: handle missing content-type header
docs: update API key rotation section
```

---

## Branch Naming

```
feature/<short-description>
fix/<short-description>
chore/<short-description>
```

**Examples:** `feature/add-rate-limiting`, `fix/null-payload-crash`, `chore/update-deps`

---

## Pull Request Checklist

Before opening a PR, confirm:

- [ ] All tests pass (`pytest tests/ -v`)
- [ ] No lint errors (`ruff check app/`)
- [ ] No type errors (`mypy app/ --ignore-missing-imports`)
- [ ] Code is formatted (`ruff format --check app/`)
- [ ] Documentation is updated (if applicable)
- [ ] Commit messages follow Conventional Commits
- [ ] PR description clearly explains the change and motivation

---

## Questions?

Open an [issue](https://github.com/darestack/saferoute-api/issues) — we're happy to help.

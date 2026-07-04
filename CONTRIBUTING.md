# Contributing to SafeRoute API

Thanks for your interest. SafeRoute is early-stage and we welcome issues, questions, and pull requests.

## Code of conduct

Be respectful. No harassment, no spam, no low-effort comments. Violations → blocked.

## How to contribute

1. **Open an issue first** for anything nontrivial. Describe the bug, feature, or question.
2. Fork → clone → `pip install -r requirements.txt`
3. Create a `.env` with Supabase credentials
4. Run `uvicorn app.main:app --reload`
5. Make your change. Keep it small.
6. Run `ruff check .` and `mypy app/` before submitting.
7. Open a PR with a clear description of the change and why.

## Style

- Python 3.14+, type hints everywhere
- Pydantic v2 models for validation
- Keep functions under ~50 lines
- No comments unless absolutely necessary

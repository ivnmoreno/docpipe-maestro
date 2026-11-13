## Summary

Describe what changed and why.

## Related Issues

Closes #

## Type of Change

- [ ] `feat`: New feature
- [ ] `fix`: Bug fix
- [ ] `docs`: Documentation update
- [ ] `refactor`: Code refactoring
- [ ] `test`: Tests or fixtures
- [ ] `chore` / `ci`: Tooling, packaging, or CI updates

## Verification Checklist

- [ ] `uv run ruff format --check .` passes
- [ ] `uv run ruff check .` and `uv run ruff check --select S src/` pass
- [ ] `uv run mypy src tests` passes
- [ ] `uv run pytest -m reverse -v` passes (Reverse Safety Gate)
- [ ] `LITELLM_LOCAL_MODEL_COST_MAP=true uv run pytest -v --cov` passes (`>= 80%` branch coverage)
- [ ] Commit messages follow Conventional Commits (`uv run cz check`)
- [ ] No library module reads config files or hardcodes provider credentials

# JULIBOT Tests

## Running tests

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific file
pytest tests/test_auth.py -v

# Run with coverage
pytest --cov=app --cov-report=term-missing
```

## Test strategy

- **Unit tests** (`test_auth.py`, `test_conversations.py`) — fast, in-memory SQLite, no network
- **Auth tests** — register, login, token validation, protected routes
- **Conversation tests** — CRUD, chat flow, auth protection
- All tests use async fixtures with isolated database sessions

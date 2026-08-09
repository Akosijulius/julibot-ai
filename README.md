# JULIBOT — AI Chat Assistant

Your Everyday AI Assistant — Faster, Smarter, More Versatile

## Overview

JULIBOT is a production-quality AI Chat Assistant built with Python and FastAPI.
It provides a personal, conversational AI experience powered by Google Gemini with
advanced features including streaming responses, intelligent context management,
and model routing.

## Features

### Core
- User authentication (signup / login with JWT)
- Conversation management (CRUD)
- AI-powered chat responses via Google Gemini
- Message history with conversation context
- Secure password handling (bcrypt)
- Guest mode (chat without an account — conversations not saved)
- Google Sign-In option
- Single-page frontend served from FastAPI

### AI & Performance
- **Streaming responses** — Real-time text display via Server-Sent Events
- **Model routing** — Automatic selection between fast/reasoning models
- **Context management** — Intelligent history pruning and token limits
- **Conversation summarization** — Automatic compression for long chats
- **Better system prompts** — Specialized modes (general, programming, reasoning, creative)
- **Parallel operations** — Background tasks for title generation
- **Rate limiting** — Protection against abuse and API quota exhaustion

### Architecture
- **LLM Provider abstraction** — Clean interface for multiple AI providers
- **AI Orchestrator** — Central coordination of AI operations
- **Structured error handling** — Typed exceptions with clear error codes
- **Structured logging** — Safe logging with secret redaction
- **Configuration validation** — Startup checks for production safety

## Tech Stack

| Layer       | Technology                                  |
| ----------- | ------------------------------------------- |
| Backend     | Python 3.13+, FastAPI 0.115                 |
| Database    | SQLAlchemy 2.0 async, SQLite (dev) / PostgreSQL (prod) |
| Auth        | JWT (python-jose), bcrypt (passlib)         |
| AI / LLM    | Google Gemini (gemini-2.0-flash, gemini-1.5-pro) |
| Frontend    | Vanilla HTML / CSS / JavaScript             |
| Streaming   | Server-Sent Events (SSE)                    |
| Testing     | pytest, pytest-asyncio, httpx               |

## Project Structure

```
julibot/
├── app/                        # Backend package
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry point
│   ├── api/                    # Route handlers
│   │   ├── auth.py             # POST /register, /login, /me, /google
│   │   ├── conversations.py    # Conversation CRUD + /chat + /chat/stream
│   │   └── deps.py             # get_current_user dependency
│   ├── core/
│   │   ├── config.py           # Settings with validation (pydantic-settings)
│   │   ├── exceptions.py       # Typed exception hierarchy
│   │   ├── logging.py          # Structured logging with secret redaction
│   │   └── security.py         # Password hashing, JWT utils
│   ├── db/
│   │   └── database.py         # Async engine + session factory
│   ├── middleware/
│   │   ├── __init__.py
│   │   └── rate_limit.py       # In-memory rate limiting
│   ├── models/
│   │   ├── user.py             # User SQLAlchemy model
│   │   └── conversation.py     # Conversation + Message models
│   ├── schemas/
│   │   ├── user.py             # Pydantic schemas for auth
│   │   └── conversation.py     # Pydantic schemas for chat
│   └── services/
│       ├── ai_orchestrator.py  # Central AI coordination
│       ├── chat_service.py     # Conversation business logic
│       ├── context_manager.py  # Token/History management
│       ├── prompts.py          # System prompts & mode routing
│       └── llm/
│           ├── __init__.py     # LLM package exports
│           ├── base.py         # Provider interface & types
│           └── gemini.py       # Google Gemini implementation
├── src/                        # Frontend
│   ├── index.html              # Main page (auth + chat views)
│   ├── css/
│   │   └── style.css           # All styles
│   ├── js/
│   │   └── app.js              # All client-side logic (with SSE support)
│   └── assets/
│       └── julibot-logo.png    # Brand logo
├── tests/
│   ├── conftest.py             # Shared fixtures (db, client, user, token)
│   ├── test_auth.py            # Auth endpoint tests
│   └── test_conversations.py   # Conversation tests
├── .env.example                # Environment template
├── requirements.txt            # Runtime Python dependencies
├── requirements-dev.txt        # Dev/test dependencies (pytest, lint, etc.)
├── pytest.ini                  # pytest configuration
└── README.md                   # This file
```

## Setup

### Prerequisites

- Python 3.13+
- (Optional) PostgreSQL for production — SQLite works out of the box for development

### Installation

```bash
# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy .env.example .env         # Windows
# cp .env.example .env         # macOS / Linux
# Edit .env and add your GOOGLE_API_KEY (free at https://aistudio.google.com/apikey)
```

### Running

```bash
# Start the server (recommended — reads HOST/PORT from .env automatically)
python run.py

# Open in browser
# http://localhost:8000          — Chat UI
# http://localhost:8000/docs     — Swagger API docs
```

Other ways to start:

```bash
python -m app           # same as python run.py
python run.py --reload  # hot-reload while developing (⚠️ see note below)
python run.py --open    # also opens the browser automatically
```

> **⚠️ About `--reload`:** On Windows, the uvicorn reloader can leave orphan
> processes holding port 8000 after you close the terminal. This is the #1 cause
> of "localhost refuses to connect." The default (`python run.py` without
> `--reload`) is a stable single process with no orphan risk. Use `--reload`
> only when actively writing code, and close the terminal properly when done.

### Testing

```bash
# Run all tests
pytest

# Verbose output
pytest -v

# With coverage
pytest --cov=app --cov-report=term-missing
```

## API Endpoints

All API routes are prefixed with `/api`.

### Authentication

| Method | Endpoint              | Description               |
| ------ | --------------------- | ------------------------- |
| POST   | `/api/auth/register`  | Create a new account      |
| POST   | `/api/auth/login`     | Login, returns JWT token  |
| GET    | `/api/auth/me`        | Current user profile      |

### Conversations

| Method | Endpoint                        | Description                      |
| ------ | ------------------------------- | -------------------------------- |
| POST   | `/api/conversations/`           | Create a new conversation        |
| GET    | `/api/conversations/`           | List user's conversations        |
| GET    | `/api/conversations/{id}`       | Get conversation with messages   |
| PATCH  | `/api/conversations/{id}`       | Update conversation title        |
| DELETE | `/api/conversations/{id}`       | Delete a conversation            |
| POST   | `/api/conversations/chat`       | Send a message, get AI response  |
| POST   | `/api/conversations/chat/stream` | Streaming AI response (SSE)      |
| POST   | `/api/conversations/import`     | Import guest conversations       |

### Information

| Method | Endpoint        | Description                    |
| ------ | --------------- | ------------------------------ |
| GET    | `/api/health`   | Health check                   |
| GET    | `/api/config`   | Public configuration           |
| GET    | `/api/models`   | List available AI models       |
| GET    | `/`             | Serve frontend                 |

## Environment Variables

| Variable                    | Required          | Description                           |
| --------------------------- | ----------------- | ------------------------------------- |
| `ENVIRONMENT`               | No                | `development`, `staging`, `production`|
| `DATABASE_URL`              | Yes               | `sqlite:///./julibot.db` (default)    |
| `SECRET_KEY`                | Yes               | JWT signing key (generate randomly)   |
| `GOOGLE_API_KEY`            | No*               | Google Gemini key (*chat needs it)    |
| `LLM_FAST_MODEL`           | No                | Model for simple tasks (default: gemini-2.0-flash) |
| `LLM_REASONING_MODEL`      | No                | Model for complex tasks (default: gemini-1.5-pro) |
| `LLM_DEFAULT_MODEL`        | No                | Default model (default: gemini-2.0-flash) |
| `MAX_HISTORY_MESSAGES`      | No                | Max messages in context (default: 20) |
| `MAX_CONTEXT_TOKENS`        | No                | Approx token limit (default: 30000)  |
| `ENABLE_SUMMARIZATION`      | No                | Summarize old messages (default: true)|
| `ENABLE_STREAMING`          | No                | Enable SSE streaming (default: true) |
| `RATE_LIMIT_CHAT`           | No                | Chat requests/min (default: 20)       |
| `RATE_LIMIT_AUTH`           | No                | Auth requests/min (default: 10)       |
| `DEBUG`                     | No                | `True` for dev, `False` for prod      |

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Architecture

### AI Orchestration

```
User Request
    ↓
AI Orchestrator
    ↓
Mode Classification (general/programming/reasoning/creative)
    ↓
Model Selection (fast/reasoning based on task)
    ↓
Context Management (history pruning, token limits)
    ↓
LLM Provider (Gemini, future: OpenAI, Anthropic)
    ↓
Response (streaming or complete)
```

### Model Routing

| Mode | Model | Use Case |
|------|-------|----------|
| General | gemini-2.0-flash | Everyday questions, simple tasks |
| Programming | gemini-2.5-pro-preview-06-05 | Code, debugging, technical |
| Reasoning | gemini-2.5-pro-preview-06-05 | Analysis, planning, complex tasks |
| Creative | gemini-2.0-flash | Writing, drafting, creative work |

## Security

- Passwords are hashed with **bcrypt** via `passlib`
- JWT tokens expire after **30 minutes** (configurable)
- `SECRET_KEY` is never committed — loaded from `.env`
- All auth routes require a valid `Authorization: Bearer <token>` header
- User data is scoped: users can only access their own conversations
- **Rate limiting** on all endpoints
- **Secret redaction** in logs
- **Input validation** on all endpoints
- **Configuration validation** at startup

## Development

### Code Quality

```bash
# Format code
black app/ tests/

# Sort imports
isort app/ tests/

# Lint
flake8 app/ tests/

# Type check
mypy app/
```

### Adding a New LLM Provider

1. Create `app/services/llm/new_provider.py`
2. Implement `LLMProvider` interface
3. Add to `app/services/llm/__init__.py`
4. Update `app/services/ai_orchestrator.py` provider selection
5. Add configuration to `app/core/config.py`

## Troubleshooting

### "Connection refused" when opening localhost

1. **Server isn't running.** Open a terminal in the project folder and run `python run.py`.
2. **Port 8000 is held by an old process.** This happens when you close a terminal without waiting for `Ctrl+C` to finish, or after a crash. Run:
   ```bash
   # Windows
   taskkill /F /PID <PID>
   # or let run.py handle it:
   python run.py --force
   ```
3. **You opened `src/index.html` directly via `file://`.** The browser can't reach the API. Always open via `http://localhost:8000`.
4. **Antivirus or firewall** is blocking Python. Add an exception for `venv/Scripts/python.exe`.

### "Database is locked" errors under load

SQLite only supports one writer at a time. The background title-generation task can clash with a concurrent streaming request. If this happens, it resolves on retry. For heavy production use, switch to PostgreSQL by setting `DATABASE_URL` in `.env`.

### Slow first response

The first chat request on a cold start is slower because the AI orchestrator initializes its provider connections. Subsequent requests are fast.

## License

MIT

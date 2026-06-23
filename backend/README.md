# Backend — AI Agent Control Tower

This is the FastAPI backend for the AI Agent Control Tower. For the full product
overview, setup guide, demo walkthrough, and roadmap, see the
[root README](../README.md).

## Quick start

```bash
# from this directory (backend/)
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
# source .venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
copy .env.example .env            # then edit DATABASE_URL / JWT_SECRET_KEY

alembic upgrade head              # create tables
python -m app.seed                # load demo data
uvicorn app.main:app --reload     # run the API
```

Then open Swagger at **http://localhost:8000/docs**.

## Layout

| Path             | Purpose                                          |
| ---------------- | ------------------------------------------------ |
| `app/core/`      | config, database session, security, enums        |
| `app/models/`    | SQLAlchemy ORM models (the 7 tables)              |
| `app/schemas/`   | Pydantic request/response models                  |
| `app/api/routes/`| HTTP routes (thin — delegate to services)         |
| `app/services/`  | business logic (permission / risk / decision / …) |
| `migrations/`    | Alembic environment and versioned migrations      |
| `tests/`         | unit tests for the engines                        |

## Tests

```bash
pytest
```

# QueuePilot

**Smarter Queues. Less Waiting.**
Machine Learning-Based Smart Queue Management and Service Time Prediction System.

> **Status: Phase 1 of 10 (foundation).** Only the project skeleton, health checks and
> UI shell exist so far. Queue features, authentication and ML arrive in later phases.
> This README documents only commands that exist in the current code.

## Stack
React + Vite (frontend) · Flask + SQLAlchemy + Flask-Migrate + JWT + CORS + Limiter (backend) · PostgreSQL.
No Docker, Redis or other infrastructure. ML libraries are added in Phase 5.

## Layout
```
backend/   Flask app (app/ factory, config, extensions, routes, models, services, ml, utils), tests/, migrations/
frontend/  React app (components, layouts, pages, services, hooks, styles)
data/      Lightweight data only (generated datasets are git-ignored)
docs/      Documentation
```

## Requirements
Python 3.11+, Node.js 18+, PostgreSQL 14+ (local Windows install), Git.

## 1. PostgreSQL setup (Windows)
Install PostgreSQL, then in **SQL Shell (psql)** as the `postgres` user:
```sql
CREATE USER queuepilot_user WITH PASSWORD 'choose_a_strong_password';
CREATE DATABASE queuepilot OWNER queuepilot_user;
```

## 2. Environment
```
copy .env.example backend\.env
```
Edit `backend\.env`: set `DATABASE_URL` with your password, and generate secrets with
`python -c "import secrets; print(secrets.token_hex(32))"` for `SECRET_KEY` and `JWT_SECRET_KEY`.
The app refuses to start if these are missing. **Never commit `.env`.**

## 3. Backend
```
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python run.py
```
Runs at http://127.0.0.1:5000.
- `GET /api/health` - API liveness (no database access)
- `GET /api/health/db` - runs `SELECT 1`; returns 503 if the database is unreachable

Migrations: the `migrations/` folder is initialised, but there are no models yet, so no
migration exists. The first one is created in Phase 2 (`flask db migrate` / `flask db upgrade`).

## 4. Frontend
```
cd frontend
npm install
npm run dev
```
Runs at http://localhost:5173 and proxies `/api` to the backend. Optionally set
`VITE_API_BASE_URL` (see `frontend/.env.example`).

## 5. Tests
```
cd backend && pytest
cd frontend && npm test
```
Backend tests use in-memory SQLite for speed; the real PostgreSQL connection is verified
manually via `/api/health/db` (the home page shows both statuses).

## Verifying Phase 1
1. Backend running, then open http://127.0.0.1:5000/api/health -> `status: ok`.
2. http://127.0.0.1:5000/api/health/db -> `database: connected`, `dialect: postgresql`.
3. Frontend home page shows **API server: Online** and **PostgreSQL database: Online**.

## Git workflow
One branch and one pull request per phase (`phase-01-foundation` ... `phase-10-finalization`),
always branched from the latest `main`. See `docs/git-workflow.md`.

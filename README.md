# QueuePilot

**Smarter Queues. Less Waiting.**
Machine Learning-Based Smart Queue Management and Service Time Prediction System.

> **Status: Phase 2 of 10 (authentication and roles).** Foundation, registration/login,
> JWT auth, role-based access and admin user management exist. Queue features and ML
> arrive in later phases.
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

### Database migrations
```
flask db upgrade
```
Run from `backend/` with the venv active (`FLASK_APP=run.py` is read from `.env`). This creates
the `users` and `token_blocklist` tables. When you change models later:
`flask db migrate -m "message"`, review the generated file, then `flask db upgrade`.

### Create the first administrator
Public registration can only create CUSTOMER accounts. Bootstrap an admin from the command line:
```
flask create-admin
```
You are prompted for name, email and a password (8+ characters, a letter and a number).
Admins then create STAFF accounts (and further admins) in the app under **Users**.

### Auth API
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/auth/register` | public | Always creates a CUSTOMER; any `role` in the body is ignored. 5/min limit |
| POST | `/api/auth/login` | public | Returns `access_token` + user. 10/min limit |
| POST | `/api/auth/logout` | any logged-in user | Revokes the token (stored in `token_blocklist`) |
| GET | `/api/auth/me` | any logged-in user | Current user |
| GET | `/api/users` | ADMIN | `search`, `role`, `status`, `page`, `per_page` |
| GET | `/api/users/<id>` | ADMIN | |
| POST | `/api/users` | ADMIN | Create a user with any role |
| PATCH | `/api/users/<id>` | ADMIN | name, phone, role, status. Admins cannot change their own role/status |

Authorization reads the user's role and status from the database on every request (not from the
token), so role changes and deactivation take effect immediately. Frontend route guards are for
user experience only; the backend is the authority.

Token storage: the access token is kept in `localStorage` (simple for a student project, but readable
by any script injected through XSS). A production deployment should prefer httpOnly cookies.

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
Backend tests use in-memory SQLite for speed; the real PostgreSQL connection and the migration
against PostgreSQL are verified manually (`flask db upgrade`, then `/api/health/db`).

## Verifying Phase 2 (manual, on PostgreSQL)
1. `flask db upgrade` succeeds; `flask create-admin` creates an admin.
2. Open http://localhost:5173, register a customer: you land on the Customer dashboard.
3. Visit `/admin/users` as that customer: **Access denied**. Log out.
4. Log in as the admin: open **Users**, create a STAFF account, change a role, deactivate a user.
5. The deactivated user can no longer log in, and an already-open session of theirs stops working.

## Git workflow
One branch and one pull request per phase (`phase-01-foundation` ... `phase-10-finalization`),
always branched from the latest `main`. See `docs/git-workflow.md`.

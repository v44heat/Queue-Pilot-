# QueuePilot

**Smarter Queues. Less Waiting.**
Machine Learning-Based Smart Queue Management and Service Time Prediction System.

> **Status: Phase 3 of 10 (core queue management).** Foundation, authentication/roles and
> the backend queue engine (services, tickets, numbering, positions, cancellation, history)
> exist. Staff workflows, ML predictions and the customer/admin queue screens arrive in later phases.
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
the `users`, `token_blocklist`, `services`, `queue_counters` and `queue_tickets` tables. When you change models later:
`flask db migrate -m "message"`, review the generated file, then `flask db upgrade`.

### Create the first administrator
Public registration can only create CUSTOMER accounts. Bootstrap an admin from the command line:
```
flask create-admin
```
You are prompted for name, email and a password (8+ characters, a letter and a number).
Admins then create STAFF accounts (and further admins) in the app under **Users**.

### Seed the demo services
```
flask seed-services
```
Creates General Enquiry (GEN), Payments (PAY), Registration (REG), Technical Support (TEC) and
Document Collection (DOC). Safe to run repeatedly. The default durations are demo estimates.

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

### Queue API (Phase 3)
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/services` | logged in | Active services with a live `waiting_count` |
| GET | `/api/services/<id>` | logged in | |
| POST | `/api/queue/join` | CUSTOMER | Body `{"service_id": 1}`. 201 with the ticket; 409 if already queued for that service |
| GET | `/api/queue/my-active` | CUSTOMER | Own WAITING/CALLED/SERVING tickets with live position |
| GET | `/api/queue/history` | CUSTOMER | Own tickets, newest first. `status`, `page`, `per_page` |
| GET | `/api/queue/tickets/<id>` | owner, STAFF, ADMIN | Another customer's ticket returns 404 |
| POST | `/api/queue/tickets/<id>/cancel` | CUSTOMER (owner) | Only while WAITING |

A ticket looks like `{"queue_number": "GEN-001", "status": "WAITING", "people_ahead": 0, "position": 1,
"predicted_waiting_time": null, ...}`. `predicted_waiting_time` is `null` until the ML pipeline exists
(Phase 5); nothing is estimated or invented before then.

**Queue rules**
- Order within a service is the ticket's (day, sequence number). *People ahead* counts only WAITING tickets
  of the same service before it; position = people ahead + 1, computed live (never stored).
- CALLED and SERVING tickets have left the waiting line. CANCELLED, SKIPPED, ABSENT and COMPLETED are
  final: the customer must join again and gets a new number.
- Allowed changes: WAITING -> CALLED | CANCELLED | SKIPPED; CALLED -> SERVING | ABSENT | SKIPPED;
  SERVING -> COMPLETED. Everything else is rejected with 409. Staff actions that drive these changes arrive in Phase 4.
- Numbers restart every local day (`APP_TIMEZONE`). Set `QUEUE_RESET_DAILY=false` for one running sequence.
  A ticket still WAITING from a previous day stays ahead of today's tickets until it is resolved.
- One active ticket per customer per service, enforced by a partial unique index in the database as well as
  in code. Ticket numbers are issued under a row lock on a per-service counter.

**Concurrency check (run on PostgreSQL).** The unit tests simulate races deterministically; to see real
simultaneous requests, run from `backend/`:
```
python scripts/concurrency_check.py --customers 30
```
It creates and then removes its own temporary service and users, and exits non-zero on any failure.

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

## Verifying Phase 3 (manual, on PostgreSQL)
1. `flask db upgrade` then `flask seed-services` succeed.
2. `python scripts/concurrency_check.py --customers 30` prints PASSED.
3. Register a customer in the app, log in, and call the API with the token (the customer screens come in Phase 6),
   e.g. with PowerShell or any API client: `POST /api/queue/join` with `{"service_id": 1}` returns `GEN-001`.
4. Join again: 409. Register a second customer and join: `GEN-002`, `people_ahead` 1.
5. Cancel the first ticket: the second customer's `people_ahead` becomes 0.
Phase 2 checks (login, role protection, user management) still apply.

## Git workflow
One branch and one pull request per phase (`phase-01-foundation` ... `phase-10-finalization`),
always branched from the latest `main`. See `docs/git-workflow.md`.

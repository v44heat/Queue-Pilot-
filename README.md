# QueuePilot

**Smarter Queues. Less Waiting.**
Machine Learning-Based Smart Queue Management and Service Time Prediction System.

> **Status: Phase 4 of 10 (staff and counters).** Foundation, authentication/roles, the backend
> queue engine and staff counter workflows (open/close, call next, start, complete, skip, absent)
> with a working staff dashboard exist. ML predictions and the customer/admin screens arrive in later phases.
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
the `users`, `token_blocklist`, `services`, `queue_counters`, `queue_tickets`, `counters` and
`staff_counter_assignments` tables. When you change models later:
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

### Seed counters and assign staff
```
flask seed-counters
flask assign-staff --email staff@example.com --counter-id 1
```
`seed-counters` creates one CLOSED counter per service ("GEN Counter 1", ...). `assign-staff` links an existing
STAFF account to a counter. (Admins can also do both through the API below; the admin screens arrive in Phase 7.)

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

### Counter and staff API (Phase 4)
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/counters` | ADMIN | All counters with assigned staff, availability, current customer |
| POST | `/api/counters` | ADMIN | `{"name", "service_id"?, "status"?}` (status CLOSED or INACTIVE) |
| PATCH | `/api/counters/<id>` | ADMIN | name, service_id, status. 409 while a customer is at the counter |
| POST | `/api/counters/<id>/staff` | ADMIN | `{"staff_id"}` must be an active STAFF account |
| DELETE | `/api/counters/<id>/staff/<staff_id>` | ADMIN | Blocked for the only staff member while serving |
| GET | `/api/staff/counters` | STAFF | Only the counters assigned to you |
| GET | `/api/staff/counters/<id>/queue` | STAFF | Waiting list, current customer, today's real statistics |
| POST | `/api/staff/counters/<id>/open` / `close` | STAFF | Cannot close while a customer is present |
| POST | `/api/staff/counters/<id>/call-next` | STAFF | Calls the first WAITING ticket of the counter's service |
| POST | `/api/staff/tickets/<id>/start` / `complete` / `skip` / `absent` | STAFF | Lifecycle actions |

Counter states: OPEN (operating), CLOSED (default; staff can open it), INACTIVE (disabled by an admin).
"Busy" is derived: a counter holding a CALLED or SERVING ticket. `GET /api/services` now also reports, per service,
how many counters are `open`, `busy` and `available` (used by the ML features in Phase 5).

**Staff rules**
- Staff act only on counters they are assigned to (others return 404). Admins configure counters but cannot open
  them or call/serve customers: those actions are staff-only.
- Call-next uses an atomic compare-and-set, so two staff can never call the same ticket; a database index also
  guarantees a counter never holds two CALLED/SERVING customers.
- When service starts, `actual_waiting_time = service_start_time - join_time`. When it completes,
  `service_duration = service_end_time - service_start_time`. Both are stored in minutes (2 decimals) and come
  from server-recorded UTC timestamps.
- A counter serves one service (`counters.service_id`). Counters serving several services are not supported.
- Statistics ("served today", average service time) count completed tickets since the start of the local day
  (`APP_TIMEZONE`).

**Staff concurrency check (run on PostgreSQL).** From `backend/`:
```
python scripts/staff_concurrency_check.py --counters 8
```
It fires simultaneous call-next requests from many counters (each must get a different ticket) and from several
staff sharing one counter (exactly one may succeed), then deletes its temporary data.

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

## Verifying Phase 4 (manual, on PostgreSQL)
1. `flask db upgrade`, `flask seed-services`, `flask seed-counters` succeed; `flask create-admin` if you have no admin.
2. Log in as the admin, create a STAFF user under **Users**, then `flask assign-staff --email <that email> --counter-id 1`.
3. `python scripts/staff_concurrency_check.py --counters 8` prints PASSED.
4. In two browsers: a customer joins a queue via the API (customer screens come in Phase 6); the staff member
   opens `/staff`, clicks **Open counter**, then **Call next customer**, **Start service**, **Complete service**.
5. The staff dashboard's stats and the customer's `GET /api/queue/history` show the recorded waiting time and
   service duration. **Skip** / **Mark absent** free the counter for the next customer.

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

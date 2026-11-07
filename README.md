# QueuePilot

**Smarter Queues. Less Waiting.**
Machine Learning-Based Smart Queue Management and Service Time Prediction System.

> **Status: Phase 8 of 10 (analytics and recommendations).** Foundation, authentication/roles, the queue engine,
> staff workflows, the waiting-time prediction pipeline, the customer application, the administration interface
> and now analytics charts, explainable counter recommendations and CSV reports exist. Testing/security hardening
> is Phase 9; final integration, demo data and documentation is Phase 10.
> This README documents only commands that exist in the current code.

## Stack
React + Vite (frontend) · Flask + SQLAlchemy + Flask-Migrate + JWT + CORS + Limiter (backend) · PostgreSQL.
No Docker, Redis or other infrastructure. ML: pandas, NumPy, scikit-learn, joblib (matplotlib is not used yet).

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
STAFF account to a counter. (Admins can also do both on the Counters page, or through the API below.)

### Machine learning: train, compare, activate
```
flask ml-train --activate-best
```
Generates 6000 reproducible **synthetic** records, trains Linear Regression, Random Forest and Gradient Boosting on
the earliest 60% of days, picks the best on the next 20% (validation MAE), and reports MAE / RMSE / R² on the final
20% of days that no model ever saw, next to a rule-based baseline. Takes about 5 seconds. Options: `--source
synthetic|historical|mixed`, `--rows`, `--seed`. Model files go to `ML_ARTIFACT_DIR` (git-ignored); the comparison is
stored in the `model_versions` table. Without `--activate-best`, activate a model through the API below.
```
flask ml-generate-data --rows 6000 --seed 42 --out ../data/synthetic_waiting_times.csv
```
writes the dataset as CSV (a 300-row sample is committed as `data/sample_synthetic_waiting_times.csv`).
**Synthetic data is for development and demonstration only; its scores say nothing about real-world accuracy.**
Full method, assumptions and limitations: [docs/ml-methodology.md](docs/ml-methodology.md).

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

### Prediction and ML API (Phase 5)
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/predictions/waiting-time` | logged in | `{"service_id": 2}`. Features come from live database state. STAFF/ADMIN may add `people_ahead`, `queue_length`, `active_counters`, `busy_counters` for a what-if scenario |
| GET | `/api/ml/models` | ADMIN | All trained versions with held-out metrics |
| POST | `/api/ml/train` | ADMIN | `{"source", "rows" (500-50000), "seed", "activate_best"}`. 6 per hour |
| POST | `/api/ml/models/<id>/activate` | ADMIN | Only eligible, loadable models; only one active at a time |
| GET | `/api/ml/performance` | ADMIN | Accuracy of predictions made by the running system, once real waits are known |
| GET | `/api/ml/prediction-logs` | ADMIN | Each prediction with its features, the actual wait and the error |

Every response says where a number came from (`source`):
- `machine_learning` - the active trained model;
- `fallback` - the documented rule (people ahead / open counters x average service time), used when no model is active
  or it cannot be loaded (`reason` says which);
- `unavailable` - no counter is open for that service, so no estimate is given rather than an invented one.

When a customer joins, the prediction is stored on the ticket (`predicted_waiting_time`) and logged with its exact
features. While the ticket waits, `estimated_wait` is a live estimate that refreshes as the queue changes; the
original prediction is kept so accuracy is always judged against what was actually promised. When service starts,
the measured wait is written next to the original prediction. A prediction failure never blocks joining a queue.

### Notifications and profile API (Phase 6)
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/notifications` | logged in | Own notifications, newest first. `unread_only=true`, `page`, `per_page`; includes `unread` |
| GET | `/api/notifications/unread-count` | logged in | `{"unread": n}` |
| POST | `/api/notifications/<id>/read` | owner | Someone else's notification returns 404 |
| POST | `/api/notifications/read-all` | logged in | |
| PATCH | `/api/auth/me` | logged in | Only `name` and `phone`; role, status and email cannot be changed here |
| POST | `/api/auth/change-password` | logged in | `{"current_password", "new_password"}`; a wrong current password is a 400 (not 401) |

**Notification rules** (stored in the database; no email/SMS provider needed)

| Type | When | Sent |
|---|---|---|
| `QUEUE_JOINED` | ticket issued; includes people ahead and the estimate if one exists | once |
| `CALLED` | staff call the ticket; names the counter (this is also the counter assignment) | once |
| `TURN_APPROACHING` | at most 2 people ahead (`notifications.approaching_ahead`), checked whenever someone ahead leaves the line | once per ticket |
| `WAIT_TIME_CHANGED` | the live estimate differs from the last one told by >= 10 minutes AND >= 25%; checked when the customer's own ticket refreshes | repeatable |
| `CANCELLED` / `SKIPPED` / `ABSENT` | ticket leaves the line without being served | once |

"Once" is enforced by a unique key in the database, so it also holds when two requests race. A notification
failure is logged and never blocks joining, calling or cancelling. The thresholds are administrator-editable system
settings (see below); the values in the table are the defaults.

### Admin API (Phase 7)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/admin/dashboard` | Summary figures, per-service congestion and counter overview |
| GET | `/api/admin/queue` | `status` (ACTIVE default, ALL or one status), `service_id`, `search`, `sort` (number, service, customer, status, joined), `order`, `page`, `per_page` |
| GET / POST | `/api/admin/services` | List with live stats / create (`name`, `prefix` 2-6 letters or digits, `default_service_duration` 1-240) |
| PATCH | `/api/admin/services/<id>` | name, prefix, description, duration, status |
| GET / PATCH | `/api/settings` | `{"settings": {"congestion.high_min": 12, "notifications.approaching_ahead": null}}` (null resets to the default) |
| GET | `/api/users` | now also `sort` (name, email, role, status, created) and `order` |

All require the ADMIN role. Counter and ML endpoints from earlier phases are used by the Counters and ML pages.

**Dashboard definitions.** "Today" is the local calendar day (`APP_TIMEZONE`). *Customers served today* = tickets completed
today. *Average waiting time* = mean measured wait of tickets whose service started today; *average service duration* =
mean duration of services completed today. Either is `null` (shown as a dash) when nothing has been measured; it is never
shown as 0. *Active counters* = counters in the OPEN state.

**Congestion levels** are computed per service from the number of waiting customers, using inclusive lower bounds that
are system settings (defaults 5 / 11 / 21): LOW below 5, MODERATE 5-10, HIGH 11-20, CRITICAL 21 or more (more than 20).
The system-wide level is the worst of the services. Thresholds must strictly increase.

### Analytics, recommendations and reports (Phase 8)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/analytics/queue-length` | `hours` (1-168), `service_id`. Per hour: customers waiting then, and the highest number waiting within that hour |
| GET | `/api/analytics/waiting-by-hour` | `days` or `from`/`to` (max 90 days), `service_id`. Average measured wait by local join hour |
| GET | `/api/analytics/daily-volume` | Per local day: joined, completed, cancelled, skipped, absent, in progress |
| GET | `/api/analytics/service-performance` | Per service: completion rate, average and longest wait, average service time |
| GET | `/api/analytics/counter-utilization` | Per counter: open minutes, serving minutes, utilization |
| GET | `/api/analytics/prediction-accuracy` | MAE, RMSE, R², daily trend and bias, predicted-vs-actual points |
| GET | `/api/analytics/recommendations` | Advisory counter recommendations (changes nothing) |
| GET | `/api/reports/daily` `weekly` `monthly` `services` `counters` `models` | CSV. `date`, `month` (YYYY-MM), or `from`/`to` |

All require ADMIN. Ranges are local calendar days and limited to 90 days (aggregation is done in Python, fine for one site).

**How the figures are defined**
- *Day* = tickets that **joined** that local day, in their current state. *Waiting time by hour* groups by join hour and uses only measured waits.
- *Queue length* is reconstructed from each ticket's join time and the moment it left the waiting line (`wait_ended_time`, recorded since
  Phase 8; backfilled for tickets already called). Cancelled or skipped tickets from before Phase 8 have no leave time and are omitted. Each point
  shows the count at that moment and the highest count at any moment within the hour, so brief spikes are not missed.
- *Counter utilization* = minutes spent serving customers / minutes the counter was open, both within the period. Opening times come from
  `counter_sessions` (written when staff open and close a counter, or an admin takes it out of service; counters open at upgrade time get a session
  starting then). A counter with no recorded open time shows *unknown*, never 0%. Time between calling and starting a customer is not counted as serving.
- *Prediction accuracy* covers predictions made in the period whose customer has started service. R² is shown only from 10 measured predictions
  (with fewer it is dominated by noise); MAE and RMSE are shown from the first. *Bias* = average(predicted - actual): positive means customers were told
  longer than they waited.

**Counter recommendations (explainable rules).** For each active service, a recommendation to **open a counter** is made when any of these holds:
1. no counter is open while customers are waiting;
2. congestion is HIGH or CRITICAL (same inclusive thresholds as the dashboard);
3. a new customer's estimated wait is at least `recommendations.wait_threshold_minutes` (default 30);
4. arrivals outpace service: arrivals per hour x recent average service minutes / 60 / open counters is at least 1 while people are waiting
   (arrivals measured over the last `recommendations.arrival_window_minutes`, default 30).

It suggests 1 additional counter (2 when CRITICAL), never more than the closed counters that have an active staff member assigned; with none, the advice is
to assign staff. Priority is URGENT (rule 1, or CRITICAL), HIGH (HIGH congestion or an estimate of at least twice the threshold) or MEDIUM. Every
recommendation lists the facts that triggered it and the data behind it. It is advisory: nothing is opened automatically, and no amount of waiting-time
reduction is promised.

**CSV reports** use the same queries as the analytics, so figures agree. Files are UTF-8 with a byte-order mark (Excel-friendly). Text cells that start
with `=`, `+`, `-` or `@` get a leading apostrophe so a service named like a formula cannot execute in a spreadsheet. Daily/weekly/monthly reports list one
row per day and service that had tickets (weekly is the Monday-to-Sunday week containing the date).

**System settings** (`system_settings` table; a missing row means the default): `congestion.moderate_min`,
`congestion.high_min`, `congestion.critical_min`, `notifications.approaching_ahead`, `notifications.wait_change_minutes`,
`notifications.wait_change_ratio`, `recommendations.wait_threshold_minutes`, `recommendations.arrival_window_minutes`.
Values are validated for type and range; an invalid change rejects the whole request.

The live monitor computes each waiting ticket's estimate with the same model and features as the customer's own ticket
page, but once per service per request rather than once per row.

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

### Admin screens (log in as an ADMIN)
| Page | Path | What it does |
|---|---|---|
| Dashboard | `/admin` | Customers served today, waiting, being served, average wait and service time, active counters, congestion level; per-service and per-counter tables. Refreshes every 5 s |
| Live queue | `/admin/queue` | Queue Number, Service, Customer, Position, Estimated Wait, Status, Counter. Search, status/service filters, sortable columns, paging, 5 s refresh |
| Services | `/admin/services` | Create, edit, deactivate/activate (never deleted) |
| Counters | `/admin/counters` | Create counters, set their service, assign/remove staff, deactivate/re-enable |
| Users | `/admin/users` | Create staff/admin accounts, change roles, activate/deactivate; search, filters, sorting, paging |
| ML models | `/admin/ml` | Held-out metrics per run with the rule-based baseline, activate a model, live accuracy, prediction errors |
| ML training | `/admin/ml/training` | Train and compare the three algorithms on synthetic, historical or mixed data |
| Analytics | `/admin/analytics` | Queue length over time, waiting time by hour, customers per day, service performance, counter utilization, prediction accuracy and error trend, predicted-vs-actual. Each chart has a data table |
| Recommendations | `/admin/recommendations` | Per service: advice, the reasons, and the data behind it. Advisory only |
| Reports | `/admin/reports` | Download CSV: daily, weekly, monthly, service performance, counter performance, ML model performance |
| Settings | `/admin/settings` | Congestion, notification and recommendation thresholds (validated, saved all-or-nothing, resettable) |

Destructive or high-impact actions (deactivating, removing staff, changing roles, activating a model) use a confirmation
dialog. Administrators cannot bypass business rules: they cannot open counters or call/serve customers, cannot deactivate
a service while customers are queued for it, cannot change a service prefix once tickets exist, and cannot change their
own role or status. Staff management is split across **Users** (accounts) and **Counters** (assignments).

### Customer screens (log in as a CUSTOMER)
| Page | Path | What it does |
|---|---|---|
| Dashboard | `/customer` | Your active tickets (live) and recent history |
| Services | `/customer/services` | Real waiting counts and open counters; **Join Queue** |
| Ticket | `/customer/tickets/<id>` | Digital ticket: number, service, people ahead, estimated wait, status, progress; cancel with confirmation |
| History | `/customer/history` | All your tickets with predicted vs actual wait; status filter, paging |
| Notifications | `/customer/notifications` | Inbox, mark read / all read, unread filter; sidebar badge |
| Profile | `/customer/profile` | Edit name and phone, change password |

Active tickets refresh every 10 seconds and polling stops once a ticket is finished; the notification badge refreshes
every 15 seconds (a toast announces new arrivals). The estimate shows its source: prediction model, basic estimate
(model not active), or "not available" when no counter is open. The layout is responsive (the sidebar becomes a
scrollable top bar on phones) but has not been checked on a physical device.

## 5. Tests
```
cd backend && pytest
cd frontend && npm test
```
Backend tests use in-memory SQLite for speed; the real PostgreSQL connection and the migration
against PostgreSQL are verified manually (`flask db upgrade`, then `/api/health/db`).

## Verifying Phase 8 (manual, on PostgreSQL)
1. `flask db upgrade` applies the migration (it backfills leave times for already-called tickets and starts a session for counters that are open);
   `pytest` and `npm test` pass.
2. With a trained, active model and a staffed counter, have several customers join, then serve some, cancel one, and skip or mark one absent.
3. **Analytics**: queue length shows the count over time and the highest within each hour; customers per day shows completed, cancelled, skipped and
   absent; service performance and counter utilization match what you did. Open "View data table" under any chart to see the exact numbers.
4. **Recommendations**: in **Settings** set the congestion thresholds low (for example 2 / 4 / 6) and the wait threshold to 5. With a few customers waiting
   a recommendation appears with its reasons. Assign staff to a second, closed counter and it is named as a candidate. Nothing opens by itself.
5. **Reports**: download each CSV and open it in Excel. Create a service named `=1+1` and download the services report: the name appears as text, not as 2.
6. Counters you never opened show utilization as unknown (a dash), not 0%.

## Verifying Phase 7 (manual, on PostgreSQL)
1. `flask db upgrade` applies the `system_settings` migration; `pytest` and `npm test` pass.
2. Log in as the admin. **Dashboard** shows dashes for the averages and congestion LOW on an empty system.
3. **Services**: add a service (prefix is upper-cased); try a duplicate prefix (refused). **Counters**: create a counter for it, assign a
   staff member, then in another browser log in as that staff member, open the counter and have customers join.
4. **Dashboard** and **Live queue** update within about 5 seconds: waiting count, positions, estimated waits, congestion level.
   Sort by Customer, search by name, filter by status.
5. **Settings**: set the congestion thresholds to 2 / 4 / 6: the dashboard level rises immediately. Try 4 / 3 / 6: the save is refused with a
   message beside the field and nothing changes. **Reset to default** restores 5 / 11 / 21.
6. Try to deactivate a service that has customers waiting: refused with the number of customers. After they are served or cancelled it succeeds.
7. **ML training**: train on synthetic data; **ML models**: compare the runs, activate one (confirmation dialog), then check **Prediction errors**
   after some customers have started service.
8. **Users**: change a role through the confirmation dialog; confirm you cannot change your own role.

## Verifying Phase 6 (manual, on PostgreSQL)
1. `flask db upgrade`, then `pytest` and `npm test` pass. Have a trained, active model (`flask ml-train --activate-best`),
   a counter with an assigned staff member (Phase 4 steps), and open the counter from the staff dashboard.
2. Register two customers in two browsers (or one normal and one private window). Customer A: **Services -> Join Queue**.
   The ticket page shows the number, people ahead, estimated wait (with its source) and progress. The **Notifications**
   badge shows 1 and the inbox has "You're in the queue".
3. Customer B joins too. As staff: **Call next customer**. Customer A's ticket changes to "Called" within about 10 seconds
   without refreshing, a toast appears, and the inbox has "It's your turn" naming the counter.
4. Staff **Start service** then **Complete service**. Customer A's ticket shows "Completed" with the real waited time and
   polling stops; **History** shows predicted vs actual.
5. Customer B: **Cancel ticket** shows a confirmation dialog; confirming cancels and creates a notification.
6. Profile: change the name (sidebar updates) and the password (old password no longer logs in).
7. Resize the window below 720 px (or use a phone) and check the ticket page and navigation.

## Verifying Phase 5 (manual, on PostgreSQL)
1. `flask db upgrade` applies the new migration; `pytest` passes.
2. `flask ml-train --activate-best` prints the three-model comparison and a baseline row, marks one model SELECTED and ACTIVE.
3. With a counter open (Phase 4 steps), have customers join: each response contains `prediction.source` =
   `machine_learning` and the model name/version. With the counter closed, `source` is `unavailable` and there is no number.
4. Staff start service; as admin, `GET /api/ml/prediction-logs?with_actual=true` shows predicted vs actual for that ticket.
5. Optional: remove the model file from `ML_ARTIFACT_DIR`; joins still work and report `fallback` / `model_unavailable`.

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

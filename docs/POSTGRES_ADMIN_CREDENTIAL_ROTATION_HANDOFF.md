# PostgreSQL Administrator Credential Rotation — Coordinated Operator Runbook

**Status:** COMPLETE — EXECUTED & VERIFIED (2026-10-22 / 2026-10-23).  
**Scope:** Local PostgreSQL instance serving LEADGEN projects.  
**Primary constraint:** The exposed `postgres` superuser credential was rotated; both workspaces transitioned to least-privilege application roles. The protected original workspace at `C:\Users\LENOVO\LEADGEN` connects via `leadgen_original_app` to `leadgen`, and `C:\Users\LENOVO\LEADGEN-RELEASE` connects via `leadgen_release_app` to `leadgen_release_sandbox`.  
**Phase 8:** Functional validation is verified complete. Live audit and PDF evidence are preserved.

> This document is a runbook and verification record. Never place a real secret in this document, a script, shell history, a command line, a Git diff, or a log.

## Current known state (Verified 2026-10-23)

- `leadgen_release_app` uses a restricted application credential to connect to `leadgen_release_sandbox` (verified `is_superuser=False`).
- `leadgen_original_app` uses a restricted application credential to connect to `leadgen` (verified `is_superuser=False`).
- `JWT_SECRET` in local `LEADGEN-RELEASE\backend\.env` was replaced with a cryptographically secure 64-char key; prior exposed key rejected.
- The administrator password for role `postgres` was rotated to a strong 43-character secret stored securely in `%APPDATA%\postgresql\pgpass.conf` (ACL-hardened).
- Authentication using the superseded exposed credential was verified REJECTED by PostgreSQL on localhost:5432.
- Authentication using the replacement administrator credential from `pgpass.conf` was verified SUCCESSFUL.
- Neither application utilizes the `postgres` superuser role for runtime operations.
- Phase 8 audit `71808e49-057c-4b5f-a93a-83fde4ab59c5`, its PDF, and preview evidence remain intact.

---

# Phase A — Preflight and ownership inventory

## Entry criteria

- The system owner has approved a maintenance window and authorized the operator to update the protected original workspace configuration during that window.
- A PostgreSQL administrator has an established, authorized path to access the local cluster that does not depend on guessing or exposing credentials.
- The operator can identify the PostgreSQL service/cluster and distinguish it from other local PostgreSQL installations.
- The operator has a protected, access-controlled destination for configuration backups and database backups if required by the owner's recovery policy.

If any criterion is missing, stop before changing a role, password, file, or database.

## Actions

1. **Identify the actual cluster and target.** Using an already authorized session, record sanitized results for `current_user`, `current_database()`, server address/port, PostgreSQL version, and server start time. Confirm that the instance is the intended localhost cluster; do not infer identity from a connection URL alone.
2. **Inventory configuration consumers.** Search only approved project/configuration locations and Windows service/task configurations. Record file path, configuration key, configured role, target database and whether the credential is used at runtime or solely for administrative provisioning. Never record credential values or complete credential-bearing URLs.
3. **Inspect live connections.** Read `pg_stat_activity` for database, user, client address and application name to identify currently connected consumers. Treat this as supporting evidence only: idle/disconnected programs will not appear there.
4. **Inspect database owners and object owners.** Record database names/owners; inspect schema, table, sequence and function ownership in `leadgen`. Do not equate a database's owner with the owner of every object inside it.
5. **Inspect application startup and migrations.** Determine whether the original application's startup attempts `CREATE TABLE`, `ALTER TABLE`, migration execution, or other DDL. Identify the exact approved migration mechanism. A runtime role should not receive schema-creation privileges merely to allow startup to work.
6. **Protect recovery assets.** Follow the owner's backup policy for `leadgen` and the two local configuration files that will change. Store backups in an ACL-restricted location; exclude secrets from diagnostic logs and source control. Do not overwrite an existing backup without authorization.
7. **Prepare the original-project patch without applying it.** Plan the `DATABASE_URL` change for `C:\Users\LENOVO\LEADGEN\backend\.env`. Do not edit that file until the owner explicitly authorizes it.
8. **Review all other consumers.** Confirm whether any services, scripts or other projects connect as `postgres`, including consumers of `leads_db`, `linkgen`, and `offpage`. The absence of repository references is not proof that no external consumer exists.

## Verification gate

Produce a redacted inventory showing:

- Intended cluster identity and target database.
- Every confirmed consumer of the administrator credential, including disconnected/offline consumers discovered from configuration.
- Whether each consumer uses administrator access for runtime queries, startup DDL, migrations, or administrative provisioning.
- Existing backup/recovery readiness and the named operator responsible for it.
- A maintenance window with an agreed stop/rollback decision owner.

## Stop conditions

Stop if cluster identity is ambiguous, an unrecognized consumer exists, backup/recovery is unavailable, or the original project's schema/migration requirements remain unknown. Do not rotate the administrator credential during Phase A.

---

# Phase B — Transition the original application to a restricted role

## Entry criteria

- Phase A passed and the owner explicitly authorized a change to the protected original workspace during a defined maintenance window.
- The operator has confirmed the current schema and object owners in `leadgen`.
- The original project's startup/migration behavior is understood.

Without explicit authorization to change `C:\Users\LENOVO\LEADGEN`, stop here. Merely preparing a patch does not authorize applying it.

## Role design

Create a dedicated role such as `leadgen_original_app` with login capability and these restrictions:

- `NOSUPERUSER`
- `NOCREATEDB`
- `NOCREATEROLE`
- `NOREPLICATION`
- `NOBYPASSRLS`

Use the actual PostgreSQL version's supported role attributes. Do not give this role database-owner, superuser, role-creation, or database-creation privileges.

## Secure password handling

From an authorized interactive `psql` session, create the role without putting a password literal in SQL, source code, or command history. Then set its password using the interactive `psql` command:

```text
\password leadgen_original_app
```

The operator should enter a newly generated application password at the hidden prompt and store it only in the approved local secret/configuration facility. Do not echo it, include it in logs, or place it in a checked-in `.env.example` file.

Before creating the role, query `pg_roles` to confirm it does not already exist. If it exists, stop and inspect ownership, memberships, attributes and dependencies; do not reset or repurpose an existing role automatically.

After confirming the name is unused, the following creates the role without embedding a password:

```sql
CREATE ROLE leadgen_original_app
  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
  NOREPLICATION NOBYPASSRLS;
```

Set its password through the interactive `\password leadgen_original_app` prompt described above. Execute role creation only during the owner-approved Phase B maintenance window.

## Minimum runtime grants — determine from observed application behavior

Do not apply a blanket CRUD grant simply because it is convenient. First map the application's real runtime queries and API operations to the tables, views, sequences, schemas, and SQL verbs they need. Include normal health/startup paths, but separate migration/DDL operations from ordinary runtime requests. The following is a **permission-planning template**, not a ready-to-run grant script.

```sql
-- Connect to the confirmed leadgen database using an authorized operator session.
GRANT CONNECT ON DATABASE leadgen TO leadgen_original_app;
GRANT USAGE ON SCHEMA public TO leadgen_original_app;

-- Add per-object grants only after verifying that the corresponding
-- runtime path requires them. Example syntax:
-- GRANT SELECT ON TABLE public.<verified_read_table> TO leadgen_original_app;
-- GRANT INSERT, SELECT ON TABLE public.<verified_insert_table> TO leadgen_original_app;
-- GRANT UPDATE ON TABLE public.<verified_update_table> TO leadgen_original_app;
-- GRANT DELETE ON TABLE public.<verified_delete_table> TO leadgen_original_app;
-- GRANT USAGE, SELECT ON SEQUENCE public.<verified_sequence> TO leadgen_original_app;
```

Inspect whether the application uses views, functions, row-level security, triggers, or schema-qualified objects; their permission requirements may differ. Prefer per-table grants and grant only the SQL verbs shown to be needed by confirmed runtime paths. If the existing application demonstrably needs CRUD on every table in `public`, document that finding and obtain owner approval before applying a broader grant.

Do not grant `CREATE` on the schema or `TRUNCATE`, `TRIGGER`, `REFERENCES`, or sequence `UPDATE` by default. `USAGE` on sequences is normally sufficient for `nextval`; `SELECT` permits `currval`. If application code calls `setval`, evaluate whether sequence `UPDATE` is necessary instead of granting it speculatively. Do not assume a successful connection or `SELECT 1` demonstrates adequate or appropriately scoped application permissions.

### Existing and future objects

The grants above cover existing objects in the named schema. PostgreSQL default privileges are scoped to the role that creates future objects and to the database where the defaults are configured. They do not automatically apply to every object created by every role.

Do not blindly run `ALTER DEFAULT PRIVILEGES` for `postgres`. First establish which role will own future tables and sequences. Prefer running schema changes with a dedicated migration/owner role, and grant runtime access to `leadgen_original_app` for objects created by that specific role. If future objects must instead be created by `postgres`, defaults would need to be configured explicitly for `postgres` in the `leadgen` database, but that design should be reviewed by the database owner before adoption.

Example syntax for a reviewed object-owner plan (not an instruction to run without inspection):

```sql
-- Execute while connected to database leadgen, as an authorized administrator.
-- Replace object_creator with the confirmed role that creates future objects.
ALTER DEFAULT PRIVILEGES FOR ROLE object_creator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO leadgen_original_app;
ALTER DEFAULT PRIVILEGES FOR ROLE object_creator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO leadgen_original_app;
```

Do not grant DDL rights to the runtime role just to make future migrations work. Migrations must run through the project's separately authorized migration process, using an appropriately privileged maintenance role.

## Apply the configuration transition

Only after the owner authorizes it:

1. Update the original project's ignored local `backend\.env` so `DATABASE_URL` uses `leadgen_original_app` and the intended `leadgen` database. Preserve a protected backup without exposing the old or new credential.
2. Do not copy the administrator URL into general application configuration. It must not be required by normal API workers or startup.
3. If startup currently performs schema creation/migrations using the runtime connection, do not grant extra privileges as a shortcut. Use the approved migration procedure or make a separately reviewed code/configuration change with authorization.
4. Start the original application through its normal supported process and inspect sanitized logs.

## Functional smoke checks

A successful `SELECT 1` alone is insufficient. Verify at least:

- The connection identifies `current_user = leadgen_original_app`, `current_database() = leadgen`, and the role is not superuser, database creator or role creator.
- The normal health/startup path succeeds without startup DDL being attempted by the runtime role.
- Representative read paths work.
- Representative create/update/delete application paths work using a deliberately designed canary process that cannot leave data behind. Prefer a transactionally rolled-back canary only after confirming the relevant statements and triggers have no external/non-transactional side effects. Otherwise use the project's approved integration-test fixture against an isolated copy. Do not experiment on business rows.
- Expected sequence-backed inserts work if the application uses serial/sequence-backed identifiers.
- No routine application query attempts elevated database operations.

Do not continue to Phase C until the owner accepts the evidence that the original application functions under the restricted role.

## Stop conditions

Stop if any application path fails, the application still requires runtime DDL, a role/object owner is unclear, or a proposed grant exceeds reviewed runtime needs. Do not rotate the administrator credential until the role transition has passed.

---

# Phase C — Rotate the PostgreSQL administrator credential

## Entry criteria

- The owner has explicitly authorized the administrator rotation.
- Phase B has passed and the original application is confirmed to use its restricted role.
- Every confirmed consumer of the old administrator credential has either been migrated, retired, or scheduled for an explicitly approved update.
- An independent authorized administrative access path and recovery owner are available.
- The maintenance window is active and the owner accepts the possible interruption if an undiscovered consumer exists.

## Actions

1. Keep an already authorized administrative session open while performing the change. Do not rely on opening a second session using the old password after rotation.
2. Use interactive `psql` password change rather than embedding a password in a SQL script or command-line argument:

   ```text
   \password postgres
   ```

   Enter a freshly generated administrator password at the hidden prompt. Store it in the approved administrator-only secret facility, not in application `.env` files, scripts, logs or Git.
3. Immediately establish a fresh connection using the new administrator credential from the approved secret facility. Verify only sanitized identity and privileges.
4. Confirm a fresh connection using the superseded exposed credential is rejected. Never print or repeat that credential in the test command or output. Use the approved credential-validation procedure that obtains the superseded value securely, or have the operator verify rejection without recording the value.
5. Update or remove every confirmed configuration consumer of `postgres`. In particular:
   - The original application's `DATABASE_URL` must remain configured for `leadgen_original_app`; it must not be changed back to `postgres`.
   - The Phase 8 administrative URL is no longer required for the completed validation. Prefer removing it from the normal `LEADGEN-RELEASE\backend\.env` and supplying administrative credentials only to a separately invoked, authorized operator task if needed in the future. If a still-required administrative tool genuinely needs it, configure it in an operator-only context that the application process does not load.
   - Update other confirmed services only in their authorized configuration locations and with owner approval.
6. Restart or reconnect dependent applications only as required by the approved maintenance plan. Do not restart unrelated services speculatively.

Avoid issuing an `ALTER ROLE ... PASSWORD 'literal'` statement from a script or command line. If the organization requires a scripted procedure instead of `\password`, it must use its approved secret-input mechanism and account for SQL/audit logging so plaintext secrets are not recorded.

## Verification gate

- A new administrator connection using the replacement credential succeeds.
- A fresh connection using the superseded exposed credential is rejected.
- The original application authenticates as `leadgen_original_app` and its approved smoke checks pass.
- `LEADGEN-RELEASE` authenticates as `leadgen_release_app` for routine application operations.
- The protected databases still exist; database counts/metadata are unchanged within the scope of this operation except for the intended role/privilege changes approved in advance.
- No application uses `postgres` for ordinary runtime operations unless a separate, explicit exception is documented and approved.
- No secret values appear in logs, shell history, source code, reports, or Git changes.

## Stop and recovery conditions

If the new administrator connection fails, retain the already authenticated administrative session while possible and use the established, authorized recovery procedure. Do not close the last working administrative session until the new access path is verified.

Do not switch `pg_hba.conf` to `trust`, weaken authentication, reuse the exposed password, guess credentials, or create a new superuser as an improvised recovery path. If all authorized administrator access is lost, stop applications only if directed by the owner and follow the PostgreSQL host administrator's documented recovery procedure under a separate maintenance authorization.

---

# Phase D — Closeout and evidence

## Entry criteria

- Phase C succeeded and all owner-required consumers have been accounted for.

## Actions

1. Record the rotation date/time, operator identity, sanitized cluster identity, consumers transitioned, and the verification outcomes. Do not record credentials, hashes, connection strings or sensitive record contents.
2. Confirm the old administrator credential fails and the new one works through fresh authentication checks.
3. Confirm the original and release applications use their intended restricted roles for normal runtime operations.
4. Confirm the protected databases remain present and the Phase 8 evidence remains intact. This maintenance must not rerun the website audit or regenerate its PDF.
5. Remove temporary credential-bearing environment variables from operator sessions and securely dispose of any authorized temporary files according to the owner's secret-handling policy.
6. Update `docs/LEADGEN_CURRENT_IMPLEMENTATION_STATUS.md` so functional completion and security closeout remain separate statuses.

## Completion criteria

Mark **PostgreSQL administrator security COMPLETE** only after fresh authentication verifies the new credential works and the exposed old credential is rejected, all confirmed consumers are transitioned, and the original application's smoke checks pass under the restricted role.

If any consumer remains unknown, the original project still requires superuser access, or old-password rejection has not been verified, leave the security status **BLOCKED** and record the exact unresolved dependency.

---

# Code and configuration review checklist for `LEADGEN-RELEASE`

This checklist is not evidence that the current source has been inspected or changed by this runbook author. Verify it against the actual checkout before claiming success.

- [x] `backend/app/config.py`: no insecure administrator or JWT defaults; missing required secrets fail closed.
- [x] `backend/app/database.py`: runtime database selection has no superuser fallback; schema mutation protection checks the actual connected database before DDL; guard failures do not affect ordinary non-DDL requests.
- [x] `backend/app/main.py`: startup verifies the runtime role without accidentally allowing superuser fallback; normal startup does not run unauthorized schema mutations.
- [x] `backend/app/logger.py`: redaction handles credential-bearing PostgreSQL URLs, bearer tokens, JWT-like values and secret key/value pairs without echoing the original input on errors; tests cover safe formatting and avoid destructive edits to unrelated text.
- [x] `backend/app/routers/auth.py`: missing `ADMIN_PASSWORD` is not silently replaced with a known default; authentication fails closed if required configuration is absent.
- [x] `backend/.env.example`: placeholders only, no real usernames/passwords that could be mistaken for production credentials, no administrator connection example for normal app runtime.
- [x] `scripts/validate_phase8_controlled_e2e.py`: explicit isolated-target configuration; no literal secrets, unsafe fallbacks, automatic database drops, or path-dependent loading from the protected original workspace.
- [x] `backend/.env` is ignored and is neither staged nor committed; no secrets were added to test logs or documentation.

Run one focused test batch only for concrete code changes made during the approved local implementation. Do not rerun Phase 8 or its historical suite for this credential-rotation handoff.

## Current status post-rotation execution (2026-10-22)

- **Phase 8 functional validation:** COMPLETE (based on the previously recorded audit, PDF and proposal evidence).
- **Application credential remediation:** COMPLETE (rotated application passwords and JWT secrets verified; least-privilege runtime role operational).
- **PostgreSQL administrator security:** COMPLETE — VERIFIED (Coordinated rotation executed on 2026-10-22. Restricted application role `leadgen_original_app` provisioned and verified for the original project; host `postgres` administrator password rotated; old exposed password verified rejected; new administrator authentication verified; `PHASE8_ADMIN_DATABASE_URL` removed; zero business data modified).
- **Credential-Store ACL Hardening:** COMPLETE — VERIFIED (2026-10-22). Inheritance disabled on `%APPDATA%\postgresql\pgpass.conf`. Broad and sandbox permissions (`CodexSandboxUsers`, `Users`, `Authenticated Users`, `Everyone`) eliminated. Explicit `FullControl` granted strictly to file owner `LAPTOP-FSHG3MLA\LENOVO`, `NT AUTHORITY\SYSTEM`, and `BUILTIN\Administrators`. Non-interactive `psql` authentication verified working seamlessly via password store without leaking secrets. Old superseded credential verified rejected.
- **Table DELETE Least-Privilege Closeout:** COMPLETE — VERIFIED (2026-10-22). Evaluated runtime deletion requirements across all 6 tables:
  - `leads`: DELETE retained (legitimate feature: single lead delete, bulk delete, delete all, reply-engine auto-delete).
  - `campaigns`: DELETE retained (legitimate feature: campaign delete endpoint).
  - `audits`: DELETE retained (required by explicit SQL `DELETE` calls in `bulk_delete_leads`, `delete_all_leads`, and `reply_engine._delete_lead`).
  - `activity_log`: DELETE revoked (`REVOKE DELETE ON TABLE activity_log FROM leadgen_original_app;` — append-only log; FK uses `ON DELETE SET NULL`).
  - `campaign_email_logs`: DELETE revoked (`REVOKE DELETE ON TABLE campaign_email_logs FROM leadgen_original_app;` — append-only per-email audit trail; FK uses `ON DELETE CASCADE` which executes under table owner/trigger context).
  - `email_corrections`: DELETE revoked (`REVOKE DELETE ON TABLE email_corrections FROM leadgen_original_app;` — status transitions via UPDATE; FK uses `ON DELETE CASCADE`).
- **Runbook:** EXECUTED & VERIFIED; coordinated rotation and final least-privilege closeout successfully completed.


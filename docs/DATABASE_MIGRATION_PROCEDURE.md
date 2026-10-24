# LEADGEN — Controlled Database Migration Procedure

This document specifies the mandatory operator procedure for applying versioned database migrations in authorized LEADGEN environments.

## Non-Negotiable Database Safety Constraints

The following production and reference databases are **strictly protected** and must never be altered by manual or automated migrations:
- `leadgen`
- `leadgen_test`
- `leads_db`
- `linkgen`
- `offpage`

### Technical Scope of the Migration SQL Preflight Guard

The SQL preflight guard in `backend/migrations/v6_2_0_email_verification.sql` through `v6_2_6_campaign_orchestration_and_locks.sql` denies execution against the protected production and system databases (`leadgen`, `leadgen_test`, `leads_db`, `linkgen`, `offpage`, `postgres`, `template0`, `template1`) by inspecting `current_database()`. The local development sandbox database `leadgen_release_sandbox` is explicitly permitted only under deliberate operator authorization with prior verified backup.

**Important Scope Distinction:**
The migration SQL itself does **not** implement a complete target whitelist, nor does it verify written authorization, target ownership, host identity, backups, or recovery readiness. The SQL guard strictly enforces a blacklist against protected production and system databases. Authorization and safety verification of any other target remains a separate, mandatory operator responsibility.

---

## 7-Step Operator Migration Protocol

Before applying any migration (such as `backend/migrations/v6_2_2_campaign_segmentation.sql`) against an authorized database, operators must execute the following sequence:

### 1. Explicit Authorization
Obtain written confirmation designating the exact target environment (e.g., release candidate sandbox) and database instance. Never assume a target.

### 2. Verify Connection Target
Inspect and confirm the actual target connection parameters (host, port, database name) before executing any DDL:
```bash
psql -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -d <AUTHORIZED_TARGET_DB> -c "SELECT current_database(), inet_server_addr(), inet_server_port();"
```

### 3. Confirm Non-Protected Target
Assert that `<AUTHORIZED_TARGET_DB>` does not match any protected or system database name (`leadgen`, `leadgen_test`, `leads_db`, `linkgen`, `offpage`, `leadgen_release_sandbox`, `postgres`, `template0`, `template1`).

### 4. Review Migration SQL & Current Schema
Inspect the table structure and verify preconditions:
```bash
psql -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -d <AUTHORIZED_TARGET_DB> -c "\d campaigns"
```
Review the migration SQL script to verify that all operations are additive, repeatable, and compatible.

### 5. Environment Backup & Recovery
Create a verified point-in-time backup of the authorized target database prior to running DDL:
```bash
pg_dump -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -Fc -d <AUTHORIZED_TARGET_DB> -f backup_pre_migration.dump
```

### 6. Deliberate Operator Application
Apply the migration script using `psql` with `-v ON_ERROR_STOP=1` inside an explicit transaction:
```bash
# WARNING: The following command is illustrative and MUST NOT be executed until steps 1-5 are completed.
psql -v ON_ERROR_STOP=1 -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -d <AUTHORIZED_TARGET_DB> -f backend/migrations/v6_2_2_campaign_segmentation.sql
```

### 7. Post-Migration Verification
Query the information schema and table metadata to confirm the migration applied cleanly:
```bash
psql -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -d <AUTHORIZED_TARGET_DB> -c "SELECT column_name, data_type, column_default FROM information_schema.columns WHERE table_name = 'campaigns' AND column_name = 'campaign_type';"
psql -h <TARGET_HOST> -p <TARGET_PORT> -U <TARGET_USER> -d <AUTHORIZED_TARGET_DB> -c "\d campaigns"
```

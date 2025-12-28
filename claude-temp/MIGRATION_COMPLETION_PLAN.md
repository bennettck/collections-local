# PostgreSQL Migration Completion Plan

**Created:** 2025-12-28
**Branch:** `claude/complete-postgres-migration-543K7`
**Objective:** Complete the SQLite/ChromaDB → PostgreSQL/PGVector migration

---

## Overview

This plan addresses the incomplete migration identified in the architecture review. The PostgreSQL implementation is production-ready but legacy SQLite code remains in active paths.

**Scope:**
- Remove SQLite from production code paths
- Clean up ChromaDB naming remnants
- Consolidate configuration
- Update tests
- Validate and clean up

**Out of Scope:**
- Lambda function updates (separate deployment concern)
- IVFFlat index creation (requires data, separate task)
- CDK pgvector extension automation (infrastructure task)

---

## Phase 1: Remove SQLite from Main Application

### Task 1.1: Update `main.py` Startup (lifespan function)

**Current State:** Lines 115-146 initialize SQLite databases for local development

**Changes:**
1. Remove SQLite initialization block (lines 118-146)
2. Keep PGVector and ConversationManager initialization
3. Remove `from database_sqlite import database_context` import
4. Remove `PROD_DATABASE_PATH` and `GOLDEN_DATABASE_PATH` for SQLite

**Files Modified:**
- `main.py`

**Risk:** Low - PostgreSQL path already exists and works

---

### Task 1.2: Remove FTS5 Sync from Analysis Endpoint

**Current State:** `main.py:505-516` syncs to SQLite FTS5 after analysis

**Changes:**
1. Remove the FTS5 sync block entirely
2. PostgreSQL tsvector is updated via trigger on analysis insert
3. Keep only the PGVector sync (lines 521-537)

**Files Modified:**
- `main.py`

**Risk:** Low - PostgreSQL trigger handles tsvector automatically

---

### Task 1.3: Update `database/api.py` to PostgreSQL-Only

**Current State:** Conditionally imports SQLite or PostgreSQL based on environment

**Changes:**
1. Remove conditional import logic (lines 21-67)
2. Always import from `database_sqlalchemy`
3. Remove SQLite-only functions that raise `NotImplementedError`
4. Simplify wrapper functions to just call PostgreSQL functions

**Files Modified:**
- `database/api.py`

**Risk:** Medium - Ensure all callers pass `user_id`

---

### Task 1.4: Update or Remove `middleware/database_routing.py`

**Current State:** Uses SQLite `database_context` - completely broken for PostgreSQL

**Changes:**
Option A (Recommended): Remove middleware entirely
- Database routing for prod/golden is better handled at the application level
- The `get_current_vector_store()` function already handles this

Option B: Update to PostgreSQL
- Would require SQLAlchemy session management per-request
- More complex, less value

**Decision Needed:** Remove or update?

**Files Modified:**
- `middleware/database_routing.py` (remove or update)
- `main.py` (remove middleware registration if removing)
- `middleware/__init__.py` (update exports)

**Risk:** Medium - Need to verify middleware is not critical

---

## Phase 2: Clean Up Legacy Files

### Task 2.1: Remove Deprecated SQLite Modules

**Files to Remove:**
```
database_sqlite.py           (~30 lines)
database_sqlite_legacy.py    (~800 lines)
```

**Validation:**
- Grep for imports of these modules
- Ensure no production code references them after Phase 1

**Risk:** Low after Phase 1 complete

---

### Task 2.2: Clean Up Archive and Migration Scripts

**Files to Remove (after validation):**
```
scripts/migrate/sqlite_to_postgres.py
scripts/migrate/chromadb_to_pgvector.py
scripts/migrate/validate_migration.py
scripts/migrate/run_migration.py
scripts/migrate/tests/
```

**Files to Keep (reference):**
```
scripts/migrate/README.md  (document migration history)
```

**Risk:** Low - Migration scripts are no longer needed

---

## Phase 3: Configuration Cleanup

### Task 3.1: Remove ChromaDB Configuration

**Files Modified:**

1. `config/langchain_config.py`
   - Remove `CHROMA_PROD_PERSIST_DIRECTORY` (line 29)
   - Remove `CHROMA_GOLDEN_PERSIST_DIRECTORY` (line 36)

2. `config/retriever_config.py`
   - Remove `CHROMA_CONFIG` dict (lines 91-113)

3. `config/__init__.py`
   - Remove `CHROMA_CONFIG` export

**Risk:** Low - Grep for usages first

---

### Task 3.2: Remove SQLite Configuration from models.py

**Current State:** `models.py:12-13` has SQLite database paths

**Changes:**
1. Remove `prod_database_path` and `golden_database_path` from Settings
2. Keep only PostgreSQL configuration

**Risk:** Low - Verify Settings class usage

---

### Task 3.3: Update CLAUDE.md

**Changes:**
1. Update embedding dimensions from 512 to 1024
2. Remove SQLite references from "Local Development" section
3. Update to reflect PostgreSQL-only architecture

**Risk:** None - Documentation only

---

## Phase 4: Update Tests

### Task 4.1: Update Test Mocks

**Files to Update:**

1. `tests/test_search_endpoint.py`
   - Rename `mock_chroma_manager` → `mock_vector_store`
   - Update patches from `main.prod_chroma_manager` → `main.prod_vector_store`
   - Remove `mock_db_context` that patches SQLite

2. Other test files referencing "chroma":
   - `tests/test_agentic_search.py`

**Risk:** Medium - Tests may fail, need to run and fix

---

### Task 4.2: Remove SQLite-Specific Test Fixtures

**Changes:**
1. Remove fixtures that create SQLite databases
2. Update integration tests to use PostgreSQL mocks

**Risk:** Medium - May need test infrastructure updates

---

## Phase 5: Validation and Cleanup

### Task 5.1: Validate No SQLite References Remain

**Validation Steps:**
```bash
# Should return no results in production code
grep -r "sqlite" --include="*.py" --exclude-dir=scripts --exclude-dir=archive
grep -r "database_sqlite" --include="*.py"
grep -r "FTS5\|items_fts" --include="*.py"
```

---

### Task 5.2: Validate No ChromaDB References Remain

**Validation Steps:**
```bash
# Should only find archive files
grep -r "chroma" --include="*.py" --exclude-dir=archive
grep -r "Chroma" --include="*.py" --exclude-dir=archive
```

---

### Task 5.3: Run Tests

```bash
pytest tests/ -v
```

---

### Task 5.4: Clean Up Temp Files

```bash
rm -rf claude-temp/
```

---

## Implementation Order

```
Phase 1: Remove SQLite from Main Application
├── 1.1 Update main.py startup
├── 1.2 Remove FTS5 sync
├── 1.3 Update database/api.py
└── 1.4 Handle middleware

Phase 2: Clean Up Legacy Files
├── 2.1 Remove SQLite modules
└── 2.2 Remove migration scripts

Phase 3: Configuration Cleanup
├── 3.1 Remove ChromaDB config
├── 3.2 Remove SQLite config
└── 3.3 Update CLAUDE.md

Phase 4: Update Tests
├── 4.1 Update test mocks
└── 4.2 Remove SQLite fixtures

Phase 5: Validation
├── 5.1 Validate no SQLite
├── 5.2 Validate no ChromaDB
├── 5.3 Run tests
└── 5.4 Cleanup
```

---

## Decision Points for Review

1. **Task 1.4 - Middleware:**
   - **Option A:** Remove `DatabaseRoutingMiddleware` entirely (recommended)
   - **Option B:** Update to use PostgreSQL sessions
   - **Question:** Is the prod/golden database routing via subdomain still needed?

2. **Task 2.2 - Migration Scripts:**
   - Keep `README.md` documenting migration history?
   - Or remove entire `scripts/migrate/` directory?

3. **Lambda Updates:**
   - Lambda functions have their own copies of database code
   - Should these be updated in this PR or separately?

---

## Rollback Plan

All changes are on branch `claude/complete-postgres-migration-543K7`.

If issues arise:
1. Revert to `main` branch
2. Cherry-pick specific fixes if partial success

---

## Estimated Impact

| Metric | Before | After |
|--------|--------|-------|
| Lines of Dead Code | ~2,100 | ~200 |
| Database Backends | 2 (SQLite + PostgreSQL) | 1 (PostgreSQL) |
| Vector Stores | 2 (archive + PGVector) | 1 (PGVector) |
| Config Constants | Mixed | PostgreSQL-only |

---

## Post-Implementation Tasks (Out of Scope)

These should be separate PRs:

1. **Infrastructure:** Add Lambda custom resource for pgvector extension
2. **Performance:** Uncomment and create IVFFlat index after data population
3. **Lambda:** Update Lambda function database code to match
4. **Connection:** Consolidate connection string loading to single location

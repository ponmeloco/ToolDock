# Production Readiness Refactoring Plan

> Generated 2026-02-07 from comprehensive codebase audit.
> Goal: Make ToolDock production-ready while keeping dev-friendly defaults (CORS=*, no TLS, SQLite).

---

## Phase 1 — Safety Net

Prevents data loss, crashes, and security holes. Do first.

### 1. Command injection via startup_command [CRITICAL]

- **File**: `app/external/fastmcp_manager.py:767-773`
- **Problem**: User-supplied `startup_command` from DB passed directly to `subprocess.Popen` without validation. Any command can be executed.
- **Fix**: Validate command against whitelist (`python`, `node`, `npx`, `uvx`, `uv`). Reject anything else unless an explicit `ALLOW_CUSTOM_COMMANDS=true` env var is set.
- **Dev default**: Whitelist only.

### 2. Hot reload leaves broken registry state [CRITICAL]

- **File**: `app/reload.py:106-141`
- **Problem**: Tools are unregistered first (`_unregister_namespace_tools`), then reload is attempted. If any tool file has a syntax error, the namespace ends up with 0 tools. Requests fail with `ToolNotFoundError` until next successful reload.
- **Fix**: Build new tool set in a temporary registry/dict first. Validate all files parse and register correctly. Only then swap: unregister old, register new. If validation fails, old tools remain active.
- **Bonus**: Add `reload_dry_run(namespace)` endpoint that validates without swapping.

### 3. Unclosed log file handles [CRITICAL]

- **File**: `app/external/fastmcp_manager.py:739`
- **Problem**: `open(log_path, "a")` is passed to `Popen(stdout=, stderr=)` but the file handle is never stored or closed. On server restart/stop, FDs accumulate. Eventually hits OS limit.
- **Fix**: Store the file handle in the server record or a dict keyed by namespace. Close it in `stop_server()` and on process restart. Use a context manager or try/finally around `Popen`.

### 4. No SIGTERM handler for graceful shutdown [CRITICAL]

- **File**: `main.py:246-255`
- **Problem**: When Docker sends SIGTERM, the process is killed without cleanup. External server children are orphaned, DB connections not closed, metrics not flushed.
- **Fix**: Add `signal.signal(signal.SIGTERM, graceful_shutdown)` in `main.py` before starting servers. The handler should:
  1. Stop all external server subprocesses (send SIGTERM, wait 5s, SIGKILL)
  2. Close log file handles
  3. Flush metrics store
  4. Close DB connections
  5. Exit cleanly

### 5. No registry locking [HIGH]

- **File**: `app/registry.py:44-49`
- **Problem**: `_tools`, `_external_tools`, `_namespaces` are plain dicts mutated during hot reload while concurrent requests read them. Can cause `KeyError`, inconsistent tool lists, or partial state.
- **Fix**: Either:
  - (a) Add `asyncio.Lock` around all mutations (register, unregister, reload), or
  - (b) Copy-on-write: build new dict, then atomic swap (`self._tools = new_tools`). Python's GIL makes single-attribute assignment atomic.
- **Recommendation**: Option (b) — simpler, no lock contention on reads.

### 6. Bare `except:` clauses [HIGH]

- **Files**:
  - `app/external/stdio_bridge.py:251, 262`
  - `app/external/http_wrapper.py:301, 319`
- **Problem**: Bare `except:` catches `SystemExit`, `KeyboardInterrupt`, `GeneratorExit`. Prevents graceful shutdown, masks bugs.
- **Fix**: Replace with `except Exception:` or specific types (`except (OSError, asyncio.CancelledError):`).

---

## Phase 2 — Resilience

Prevents hangs, silent failures, and security gaps under normal operation.

### 7. No subprocess startup timeout [HIGH]

- **File**: `app/external/fastmcp_manager.py:767`
- **Problem**: `subprocess.Popen()` + `time.sleep(0.2)` — if the server hangs on startup, the caller blocks forever.
- **Fix**: Poll loop with max wait (e.g., 10s configurable via `FASTMCP_STARTUP_TIMEOUT`). If process hasn't responded or has exited with error within timeout, mark as failed and kill.

### 8. No TLS option in nginx [HIGH]

- **File**: `admin-ui/nginx.conf`
- **Problem**: Bearer tokens sent in plaintext over HTTP. Anyone on the network can sniff them.
- **Fix**: Add optional TLS support:
  - If `SSL_CERT_PATH` and `SSL_KEY_PATH` env vars are set, nginx listens on 443 with TLS.
  - If not set, keep HTTP on port 13000 (dev default).
  - Add `nginx-ssl.conf.template` with `envsubst` for cert paths.
- **Dev default**: HTTP, no TLS.

### 9. DB init failure not fatal [HIGH]

- **File**: `main.py:83-87`
- **Problem**: Database init failure is logged as `warning`, server starts anyway. All subsequent DB operations fail with confusing errors.
- **Fix**: Change to `logger.error(...)` and `sys.exit(1)`. The server should not start if it can't reach its database.

### 10. `asyncio.run()` during app init [HIGH]

- **Files**: `app/transports/mcp_http_server.py:916-920`, `app/transports/openapi_server.py:464-468`
- **Problem**: `asyncio.run(fastmcp_manager.sync_from_db())` creates a second event loop during app construction, conflicting with uvicorn's loop.
- **Fix**: Move to FastAPI `lifespan` context manager:
  ```python
  @asynccontextmanager
  async def lifespan(app):
      if fastmcp_manager:
          await fastmcp_manager.sync_from_db()
      yield
  app = FastAPI(lifespan=lifespan)
  ```

---

## Phase 3 — Hardening

Handles edge cases under load, prevents resource exhaustion.

### 11. No rate limiting in nginx [MEDIUM]

- **File**: `admin-ui/nginx.conf`
- **Problem**: No `limit_req_zone` or `limit_conn_zone`. Any client can hammer endpoints.
- **Fix**: Add configurable rate limiting:
  ```nginx
  limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;
  limit_req zone=api burst=50 nodelay;
  ```
- **Dev default**: Disabled (`RATE_LIMIT_ENABLED=false`).

### 12. No Docker resource limits [MEDIUM]

- **File**: `docker-compose.yml:27-67`
- **Problem**: No `mem_limit` or `cpus`. A runaway external MCP server can OOM-kill the entire container.
- **Fix**: Add a `docker-compose.prod.yml` overlay:
  ```yaml
  services:
    tooldock-backend:
      deploy:
        resources:
          limits:
            memory: 2G
            cpus: '2.0'
  ```
- **Dev default**: No limits in base `docker-compose.yml`.

### 13. Silent metrics drop on SQLite lock [MEDIUM]

- **File**: `app/metrics_store.py:67-83`
- **Problem**: After 3 retries on `sqlite3.OperationalError("locked")`, batch is silently dropped. No log, no counter.
- **Fix**: Log a warning with batch size. Add `self._dropped_count` counter. Expose in `/health` response.

### 14. Orphaned asyncio tasks [MEDIUM]

- **File**: `app/external/stdio_bridge.py:106-107`
- **Problem**: `asyncio.create_task(self._log_stderr())` — no reference stored, never cancelled on shutdown.
- **Fix**: Store task reference, cancel in `close()`/`shutdown()`.

### 15. No httpx connection pool limits [MEDIUM]

- **File**: `app/external/fastmcp_proxy.py:53`
- **Problem**: `httpx.AsyncClient()` created without `limits=`. Under load with many external servers, connections accumulate.
- **Fix**: `httpx.AsyncClient(limits=httpx.Limits(max_connections=20, max_keepalive_connections=5))`.

### 16. PID reuse race condition [MEDIUM]

- **File**: `app/external/fastmcp_manager.py:1175-1191`
- **Problem**: Between checking PID is alive and sending signal, OS can reuse the PID. Wrong process killed.
- **Fix**: Use process groups (`os.setpgrp` in `preexec_fn`, `os.killpg` to terminate). Or store `subprocess.Popen` object instead of just PID.

### 17. TOCTOU in repo checkout [MEDIUM]

- **File**: `app/external/fastmcp_manager.py:966-980`
- **Problem**: `exists()` check → `rmtree()` → `git clone` has race if concurrent calls target same namespace.
- **Fix**: Use temp directory + atomic rename: `git clone` into `{repo_dir}.tmp`, then `os.rename()`.

### 18. Config writes not atomic [MEDIUM]

- **File**: `app/external/fastmcp_manager.py:224`
- **Problem**: `path.write_text()` — crash mid-write leaves corrupted file.
- **Fix**: Write to `{path}.tmp`, then `os.replace(tmp, path)` (atomic on POSIX).

### 19. Env var injection via FastMCP [MEDIUM]

- **File**: `app/external/fastmcp_manager.py:780`
- **Problem**: User-supplied env vars from `env_vars` JSON column not validated. Arbitrary key names allowed.
- **Fix**: Validate key names match `^[A-Z_][A-Z0-9_]*$`. Reject keys like `LD_PRELOAD`, `PYTHONPATH`, `PATH`.

### 20. Health check only tests MCP port [MEDIUM]

- **File**: `docker-compose.yml:61-67`
- **Problem**: `curl -f http://localhost:8007/health` — if OpenAPI (8006) or Web (8080) server dies, health still passes.
- **Fix**: Add combined health endpoint that pings all internal services. Or check all three ports in the Docker healthcheck script.

### 21. `get_db()` has no auto-commit/rollback [MEDIUM]

- **File**: `app/db/database.py:116-124`
- **Problem**: Context manager does `yield db` then `db.close()`. If caller forgets `db.commit()`, changes are lost. If exception occurs, no explicit rollback.
- **Fix**:
  ```python
  try:
      yield db
      db.commit()
  except Exception:
      db.rollback()
      raise
  finally:
      db.close()
  ```

### 22. Path traversal in deps.py [MEDIUM]

- **File**: `app/deps.py:32`
- **Problem**: `namespace` parameter used in path construction without validation: `_get_data_dir() / "venvs" / namespace`. A namespace like `../../etc` traverses out.
- **Fix**: Validate namespace matches `^[a-z0-9][a-z0-9_-]*$` at the entry point (deps.py and folders.py).

---

## Phase 4 — Observability

Polish, monitoring, long-term maintainability.

### 23. Pin dependency versions [LOW]

- **File**: `requirements.txt`
- **Problem**: Uses `>=` (e.g., `fastapi>=0.115.0`). Minor updates can break things.
- **Fix**: Generate `requirements.lock` with exact versions. Keep `requirements.txt` as loose constraints for development.

### 24. Structured JSON logging with correlation IDs [LOW]

- **Problem**: Logs use plain `logger.info(f"...")` format. Hard to correlate across services.
- **Fix**: Add `structlog` or configure stdlib logging with JSON formatter. Include `request_id` in all log entries. Pass it through headers (`X-Request-Id`).

### 25. Liveness vs readiness probes [LOW]

- **File**: `app/transports/mcp_http_server.py` `/health` endpoint
- **Problem**: Single health endpoint doesn't distinguish "server is alive" from "server is ready to serve".
- **Fix**: Add `/health/live` (always 200 if process is up) and `/health/ready` (200 only if DB is connected, tools loaded, external servers synced).

### 26. Auto-restart for crashed external servers [LOW]

- **Problem**: If an external MCP server crashes, it stays in "error" state until manually restarted.
- **Fix**: Add configurable restart policy: `FASTMCP_RESTART_POLICY=on-failure` with exponential backoff (1s, 2s, 4s, ... max 60s). After N consecutive failures, stop retrying and alert.

### 27. pip-audit in CI [LOW]

- **Problem**: No vulnerability scanning of Python dependencies.
- **Fix**: Add `pip-audit` to CI pipeline. Run on every PR.

---

## Dev-Friendly Defaults (DO NOT remove)

These keep the project easy to use for local development:

| Setting | Dev Default | Production Override |
|---------|-------------|-------------------|
| CORS | `CORS_ORIGINS=*` | Set to specific origins |
| TLS | HTTP only | Set `SSL_CERT_PATH` + `SSL_KEY_PATH` |
| Rate limiting | Disabled | `RATE_LIMIT_ENABLED=true` |
| Database | SQLite | `DATABASE_URL=postgresql+psycopg://...` |
| Resource limits | None | Use `docker-compose.prod.yml` overlay |
| Custom commands | Whitelist only | `ALLOW_CUSTOM_COMMANDS=true` |
| Log format | Plain text | `LOG_FORMAT=json` |

---

## Suggested Implementation Order

1. **Phase 1** (Safety Net): ~2-3 days. Items 1-6. Blocks production use.
2. **Phase 2** (Resilience): ~2 days. Items 7-10. Needed for reliable operation.
3. **Phase 3** (Hardening): ~3-4 days. Items 11-22. Needed for production load.
4. **Phase 4** (Observability): ~2 days. Items 23-27. Nice-to-have, ongoing.

Total estimate: ~10 days of focused work.

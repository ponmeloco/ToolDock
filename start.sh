#!/bin/bash
# ==================================================
# ToolDock Startup Script
# ==================================================
# - Checks for .env file
# - Builds Docker images (use --rebuild to force)
# - Starts the stack
# - Runs health checks
# - Runs unit tests (summary only)
#
# Usage:
#   ./start.sh           # Normal start (uses cached images)
#   ./start.sh --rebuild # Force rebuild all images
#   ./start.sh -r        # Short form
#   ./start.sh --skip-tests # Start stack without pytest
# ==================================================

set -euo pipefail

# Parse arguments
FORCE_REBUILD=false
RUN_TESTS=true
while [ $# -gt 0 ]; do
    case "$1" in
        --rebuild|-r)
            FORCE_REBUILD=true
            shift
            ;;
        --skip-tests|-s)
            RUN_TESTS=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: ./start.sh [--rebuild|-r] [--skip-tests|-s]"
            exit 1
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ==================================================
# Helper Functions
# ==================================================

print_header() {
    echo ""
    echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}══════════════════════════════════════════════════${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_info() {
    echo -e "${BLUE}→${NC} $1"
}

require_command() {
    local cmd="$1"
    local install_hint="$2"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        print_error "Missing required command: $cmd"
        print_info "$install_hint"
        exit 1
    fi
}

run_with_timeout() {
    local seconds="$1"
    shift
    if command -v timeout >/dev/null 2>&1; then
        timeout --kill-after=10 "$seconds" "$@"
        return $?
    fi
    print_warning "'timeout' command not found. Running without timeout."
    "$@"
    return $?
}

# ==================================================
# Preflight Checks
# ==================================================

print_header "Preflight Checks"

require_command "docker" "Install Docker Desktop or Docker Engine, then retry."
require_command "curl" "Install curl and retry."

if ! docker compose version >/dev/null 2>&1; then
    print_error "Docker Compose v2 plugin is required ('docker compose')."
    print_info "Install or enable Docker Compose v2, then retry."
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    print_error "Docker daemon is not reachable (is Docker running, and do you have permission?)."
    print_info "Start Docker Desktop/Engine and retry."
    exit 1
fi
print_success "Docker and Docker Compose are available"

# ==================================================
# Step 1: Check .env file
# ==================================================

print_header "Checking Environment"

if [ ! -f ".env" ]; then
    print_warning ".env file not found"

    if [ -f ".env.example" ]; then
        print_info "Creating .env from .env.example..."
        cp .env.example .env
        print_success ".env created from .env.example"
        print_warning "Please review and update .env with your settings!"
    else
        print_info "Creating minimal .env..."
        cat > .env << 'EOF'
# ToolDock Environment Configuration
# ==================================

# Docker Compose project name
COMPOSE_PROJECT_NAME=tooldock

# Authentication (CHANGE THIS!)
BEARER_TOKEN=change_me_to_a_secure_token

# Single exposed gateway port
ADMIN_PORT=13000

# MCP (strict mode defaults)
MCP_PROTOCOL_VERSION=2025-11-25
MCP_PROTOCOL_VERSIONS=2025-11-25,2025-03-26

# CORS (comma-separated origins, or * for all)
CORS_ORIGINS=*

# Data directory (host path for Admin UI display)
HOST_DATA_DIR=./tooldock_data

# Database (SQLite default, Postgres-ready)
DATABASE_URL=sqlite:////data/db/tooldock.db

# Logging
LOG_LEVEL=INFO

# Tool execution timeout (seconds)
TOOL_TIMEOUT_SECONDS=30
EOF
        print_success ".env created with default values"
        print_warning "Please update BEARER_TOKEN in .env!"
    fi
else
    print_success ".env file exists"
fi

# Source .env for port variables
set -a
source .env
set +a

# Ensure host data dir is available for UI display
if [ -z "${HOST_DATA_DIR:-}" ]; then
    HOST_DATA_DIR="${SCRIPT_DIR}/tooldock_data"
else
    # If relative, resolve against repo root for clarity
    case "$HOST_DATA_DIR" in
        /*) : ;;
        *) HOST_DATA_DIR="${SCRIPT_DIR}/${HOST_DATA_DIR}" ;;
    esac
fi
export HOST_DATA_DIR

# Check for default token warning
if grep -q "BEARER_TOKEN=change_me" .env 2>/dev/null; then
    print_warning "BEARER_TOKEN is still set to default value!"
fi

# ==================================================
# Step 2: Create Data Directories
# ==================================================

print_header "Creating Data Directories"

# Create directories that the container needs write access to
DATA_DIRS=(
    "tooldock_data/logs"
    "tooldock_data/tools/shared"
    "tooldock_data/external"
    "tooldock_data/external/servers"
    "tooldock_data/external/logs"
    "tooldock_data/config"
    "tooldock_data/db"
    "tooldock_data/venvs"
)

for dir in "${DATA_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        chmod 775 "$dir" 2>/dev/null || true
        print_success "Created $dir"
    else
        chmod 775 "$dir" 2>/dev/null || true
        print_success "$dir exists"
    fi
done

if [ ! -x tooldock_data ]; then
    chmod 775 tooldock_data 2>/dev/null || true
fi
print_success "Verified safe write permissions for data directories"

# ==================================================
# Step 3: Build Docker Images
# ==================================================

print_header "Building Docker Images"

# Build function with compact output and spinner
build_image() {
    local service=$1
    local build_args=""
    local build_status=0
    local spin_chars='⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
    local spin_index=0

    if [ "$FORCE_REBUILD" = true ]; then
        build_args="--no-cache --pull"
    fi

    print_info "Building $service..."

    # Build with progress output
    if [ -t 1 ]; then
        # Terminal: show spinner with current step
        docker compose build $service $build_args --progress=plain 2>&1 | \
            while IFS= read -r line; do
                # Get spinner character
                local spin_char="${spin_chars:$spin_index:1}"
                spin_index=$(( (spin_index + 1) % ${#spin_chars} ))
                # Show spinner + truncated line
                printf "\r\033[K  ${YELLOW}%s${NC} %.90s" "$spin_char" "$line"
            done
        build_status=${PIPESTATUS[0]}
        printf "\r\033[K"  # Clear the last line
    else
        # Non-terminal: quiet build
        docker compose build $service $build_args --quiet 2>&1
        build_status=$?
    fi

    # Check if build succeeded
    if [ $build_status -eq 0 ]; then
        print_success "$service image built"
        return 0
    else
        print_error "Failed to build $service"
        return 1
    fi
}

if [ "$FORCE_REBUILD" = true ]; then
    print_info "Force rebuild enabled (--no-cache --pull)"
fi

build_image "tooldock-backend" || exit 1
build_image "tooldock-gateway" || exit 1

# ==================================================
# Step 4: Start Stack
# ==================================================

print_header "Starting Stack"

print_info "Stopping existing containers..."
docker compose down --remove-orphans 2>/dev/null || true

print_info "Starting containers..."
# Start containers quietly (suppress all docker compose output)
docker compose up -d &> /dev/null

# Check if backend is running
if docker compose ps --status running -q tooldock-backend 2>/dev/null | grep -q .; then
    print_success "Backend container started"
else
    print_error "Backend container failed to start"
    docker compose logs tooldock-backend --tail=10
    exit 1
fi

# Check if admin is running
if docker compose ps --status running -q tooldock-gateway 2>/dev/null | grep -q .; then
    print_success "Gateway container started"
else
    print_error "Gateway container failed to start"
    docker compose logs tooldock-gateway --tail=10
    exit 1
fi

# ==================================================
# Step 5: Health Checks
# ==================================================

print_header "Running Health Checks"

# Configuration
MAX_RETRIES=60
SLEEP_INTERVAL=1
HEALTH_FAILURES=0

# Helper function for health checks with retry
wait_for_health() {
    local name="$1"
    local url="$2"
    local check_type="$3"  # "json" for JSON health endpoint, "http" for just HTTP 200
    local retry_count=0

    print_info "Waiting for $name..."

    while [ $retry_count -lt $MAX_RETRIES ]; do
        if [ "$check_type" = "json" ]; then
            # Check for JSON health response with "healthy" status
            if curl -s "$url" 2>/dev/null | grep -q '"status".*"healthy"'; then
                print_success "$name is healthy"
                return 0
            fi
        else
            # Just check for HTTP 200
            if curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null | grep -q "200"; then
                print_success "$name is accessible"
                return 0
            fi
        fi

        retry_count=$((retry_count + 1))
        printf "\r  Waiting... %d/%d seconds" "$retry_count" "$MAX_RETRIES"
        sleep $SLEEP_INTERVAL
    done

    echo ""  # New line after progress
    print_error "$name failed to start after $MAX_RETRIES seconds"
    return 1
}

# Wait a moment for containers to initialize
print_info "Giving containers time to initialize..."
sleep 2

# Check each service via single gateway port
ADMIN_PORT="${ADMIN_PORT:-13000}"

echo ""

# Backend API via gateway (must succeed)
if ! wait_for_health "Backend API via gateway (port $ADMIN_PORT)" "http://localhost:$ADMIN_PORT/health" "json"; then
    HEALTH_FAILURES=$((HEALTH_FAILURES + 1))
    print_info "Backend logs:"
    docker compose logs tooldock-backend --tail=10 2>/dev/null
fi

echo ""

# Tool API via gateway
if ! wait_for_health "Tool API via gateway (port $ADMIN_PORT)" "http://localhost:$ADMIN_PORT/openapi/health" "json"; then
    HEALTH_FAILURES=$((HEALTH_FAILURES + 1))
fi

echo ""

# MCP via gateway
if ! wait_for_health "MCP via gateway (port $ADMIN_PORT)" "http://localhost:$ADMIN_PORT/mcp/health" "json"; then
    HEALTH_FAILURES=$((HEALTH_FAILURES + 1))
fi

echo ""

# Admin UI
if ! wait_for_health "Admin UI (port $ADMIN_PORT)" "http://localhost:$ADMIN_PORT" "http"; then
    HEALTH_FAILURES=$((HEALTH_FAILURES + 1))
    print_info "Gateway logs:"
    docker compose logs tooldock-gateway --tail=10 2>/dev/null
fi

echo ""

# Summary of health checks
if [ $HEALTH_FAILURES -gt 0 ]; then
    print_error "$HEALTH_FAILURES service(s) failed to start"
else
    print_success "All services are healthy"
fi

# ==================================================
# Step 6: Run Unit Tests (optional, dev only)
# ==================================================

# Prefer running tests inside the backend container (stable Python 3.12)
if [ "$RUN_TESTS" != true ]; then
    print_info "Skipping tests (--skip-tests)"
    TEST_EXIT_CODE=0
elif docker compose ps --status running -q tooldock-backend 2>/dev/null | grep -q .; then
    print_header "Running Unit Tests"
    print_info "Running pytest inside tooldock-backend container..."

    # Use --kill-after to ensure cleanup if SIGTERM is ignored
    set +e
    TEST_OUTPUT=$(run_with_timeout 120 docker compose exec -T tooldock-backend python -m pytest tests/ -q --tb=no 2>&1)
    TEST_EXIT_CODE=$?
    set -e

    if [ $TEST_EXIT_CODE -eq 124 ] || [ $TEST_EXIT_CODE -eq 137 ]; then
        print_error "Tests timed out after 120 seconds"
        TEST_EXIT_CODE=1
    fi

    SUMMARY=$(echo "$TEST_OUTPUT" | tail -1)
    if [ $TEST_EXIT_CODE -eq 0 ]; then
        print_success "All tests passed: $SUMMARY"
    else
        print_error "Some tests failed: $SUMMARY"
        echo ""
        echo "Run 'docker compose exec -T tooldock-backend pytest tests/ -v' for details"
    fi
else
    # Fallback to host pytest if available
    if command -v pytest &> /dev/null || python -m pytest --version &> /dev/null 2>&1; then
        print_header "Running Unit Tests"
        print_info "Running pytest on host..."

        # Use --kill-after to ensure cleanup if SIGTERM is ignored
        set +e
        TEST_OUTPUT=$(run_with_timeout 120 python -m pytest tests/ -q --tb=no 2>&1)
        TEST_EXIT_CODE=$?
        set -e

        if [ $TEST_EXIT_CODE -eq 124 ] || [ $TEST_EXIT_CODE -eq 137 ]; then
            print_error "Tests timed out after 120 seconds"
            TEST_EXIT_CODE=1
        fi

        SUMMARY=$(echo "$TEST_OUTPUT" | tail -1)
        if [ $TEST_EXIT_CODE -eq 0 ]; then
            print_success "All tests passed: $SUMMARY"
        else
            print_error "Some tests failed: $SUMMARY"
            echo ""
            echo "Run 'pytest tests/ -v' for details"
        fi
    else
        # Skip tests on production servers
        print_info "Skipping tests (pytest not installed)"
        print_info "To run tests: pip install pytest pytest-asyncio"
        TEST_EXIT_CODE=0
    fi
fi

# ==================================================
# Summary
# ==================================================

print_header "Summary"

echo ""
echo "Services:"
echo "  Admin UI:     http://localhost:${ADMIN_PORT:-13000}"
echo "  Backend API:  http://localhost:${ADMIN_PORT:-13000}/api"
echo "  Tool API:     http://localhost:${ADMIN_PORT:-13000}/openapi"
echo "  MCP HTTP:     http://localhost:${ADMIN_PORT:-13000}/mcp"
echo ""
echo "MCP Strict Mode:"
echo "  GET /mcp and GET /mcp/{namespace} require Accept: text/event-stream"
echo "  Notifications-only requests return 202"
echo "  MCP-Protocol-Version validated if present"
echo ""
echo "API Docs:       http://localhost:${ADMIN_PORT:-13000}/docs"
echo ""

# Show container status
echo "Container Status:"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -10

echo ""
print_info "View logs with: docker compose logs -f"
print_info "Stop with: docker compose down"
echo ""

if [ $TEST_EXIT_CODE -eq 0 ] && [ $HEALTH_FAILURES -eq 0 ]; then
    print_success "ToolDock is ready!"
    exit 0
elif [ $HEALTH_FAILURES -gt 0 ]; then
    print_error "ToolDock started with $HEALTH_FAILURES failed service(s)"
    exit 1
else
    print_warning "ToolDock started with test failures"
    exit 1
fi

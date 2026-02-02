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
# ==================================================

set -e

# Parse arguments
FORCE_REBUILD=false
for arg in "$@"; do
    case $arg in
        --rebuild|-r)
            FORCE_REBUILD=true
            shift
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

# Authentication (CHANGE THIS!)
BEARER_TOKEN=change_me_to_a_secure_token

# Ports
OPENAPI_PORT=8006
MCP_PORT=8007
WEB_PORT=8080
ADMIN_PORT=3000

# CORS (comma-separated origins, or * for all)
CORS_ORIGINS=http://localhost:3000

# Server names
WEB_SERVER_NAME=tooldock-backend
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
    "tooldock_data/config"
)

for dir in "${DATA_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        print_success "Created $dir"
    else
        print_success "$dir exists"
    fi
done

# Ensure directories are writable by container user (UID 1000)
chmod -R a+rwX tooldock_data/ 2>/dev/null || true
print_success "Set permissions on tooldock_data/"

# ==================================================
# Step 3: Build Docker Images
# ==================================================

print_header "Building Docker Images"

# Set build options
BUILD_OPTS="--quiet"
if [ "$FORCE_REBUILD" = true ]; then
    BUILD_OPTS="--no-cache --pull"
    print_info "Force rebuild enabled (--no-cache --pull)"
fi

print_info "Building tooldock-backend..."
if docker compose build tooldock-backend $BUILD_OPTS 2>&1 | grep -v "^$"; then
    print_success "tooldock-backend image built"
else
    print_error "Failed to build tooldock-backend"
    exit 1
fi

print_info "Building tooldock-admin..."
if docker compose build tooldock-admin $BUILD_OPTS 2>&1 | grep -v "^$"; then
    print_success "tooldock-admin image built"
else
    print_error "Failed to build tooldock-admin"
    exit 1
fi

# ==================================================
# Step 4: Start Stack
# ==================================================

print_header "Starting Stack"

print_info "Stopping existing containers..."
docker compose down --remove-orphans 2>/dev/null || true

print_info "Starting containers..."
# Filter out confusing "No services to build" warning
if docker compose up -d 2>&1 | grep -v "^$" | grep -v "No services to build"; then
    print_success "Containers started"
fi
# Check if containers are actually running
if docker compose ps --status running -q | grep -q .; then
    print_success "Containers started"
else
    print_error "Failed to start containers"
    docker compose logs --tail=20
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

# Check each service
BACKEND_PORT="${WEB_PORT:-8080}"
OPENAPI_PORT="${OPENAPI_PORT:-8006}"
MCP_PORT="${MCP_PORT:-8007}"
ADMIN_PORT="${ADMIN_PORT:-3000}"

echo ""

# Backend API (must succeed)
if ! wait_for_health "Backend API (port $BACKEND_PORT)" "http://localhost:$BACKEND_PORT/health" "json"; then
    HEALTH_FAILURES=$((HEALTH_FAILURES + 1))
    print_info "Backend logs:"
    docker compose logs tooldock-backend --tail=10 2>/dev/null
fi

echo ""

# OpenAPI Server
if ! wait_for_health "OpenAPI Server (port $OPENAPI_PORT)" "http://localhost:$OPENAPI_PORT/health" "json"; then
    HEALTH_FAILURES=$((HEALTH_FAILURES + 1))
fi

echo ""

# MCP Server
if ! wait_for_health "MCP Server (port $MCP_PORT)" "http://localhost:$MCP_PORT/health" "json"; then
    HEALTH_FAILURES=$((HEALTH_FAILURES + 1))
fi

echo ""

# Admin UI
if ! wait_for_health "Admin UI (port $ADMIN_PORT)" "http://localhost:$ADMIN_PORT" "http"; then
    HEALTH_FAILURES=$((HEALTH_FAILURES + 1))
    print_info "Admin UI logs:"
    docker compose logs tooldock-admin --tail=10 2>/dev/null
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

# Only run tests if pytest is available
if command -v pytest &> /dev/null || python -m pytest --version &> /dev/null 2>&1; then
    print_header "Running Unit Tests"

    print_info "Running pytest..."

    # Run tests and capture output
    TEST_OUTPUT=$(python -m pytest tests/ -q --tb=no 2>&1)
    TEST_EXIT_CODE=$?

    # Extract summary line
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
    TEST_EXIT_CODE=0
fi

# ==================================================
# Summary
# ==================================================

print_header "Summary"

echo ""
echo "Services:"
echo "  Backend API:  http://localhost:${WEB_PORT:-8080}"
echo "  OpenAPI:      http://localhost:${OPENAPI_PORT:-8006}"
echo "  MCP HTTP:     http://localhost:${MCP_PORT:-8007}"
echo "  Admin UI:     http://localhost:${ADMIN_PORT:-3000}"
echo ""
echo "API Docs:       http://localhost:${WEB_PORT:-8080}/docs"
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

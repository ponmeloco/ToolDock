#!/bin/bash
# ==================================================
# OmniMCP Startup Script
# ==================================================
# - Checks for .env file
# - Builds Docker images
# - Starts the stack
# - Runs health checks
# - Runs unit tests (summary only)
# ==================================================

set -e

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
# OmniMCP Environment Configuration
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
WEB_SERVER_NAME=omnimcp-backend
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
# Step 2: Build Docker Images
# ==================================================

print_header "Building Docker Images"

print_info "Building omnimcp-backend..."
if docker compose build omnimcp-backend --quiet 2>&1; then
    print_success "omnimcp-backend image built"
else
    print_error "Failed to build omnimcp-backend"
    exit 1
fi

print_info "Building omnimcp-admin..."
if docker compose build omnimcp-admin --quiet 2>&1; then
    print_success "omnimcp-admin image built"
else
    print_error "Failed to build omnimcp-admin"
    exit 1
fi

# ==================================================
# Step 3: Start Stack
# ==================================================

print_header "Starting Stack"

print_info "Stopping existing containers..."
docker compose down --remove-orphans 2>/dev/null || true

print_info "Starting containers..."
if docker compose up -d 2>&1 | grep -v "^$"; then
    print_success "Containers started"
else
    print_error "Failed to start containers"
    exit 1
fi

# ==================================================
# Step 4: Health Checks
# ==================================================

print_header "Running Health Checks"

# Wait for services to be ready
print_info "Waiting for services to start..."
sleep 3

# Backend health check
BACKEND_PORT="${WEB_PORT:-8080}"
MAX_RETRIES=30
RETRY_COUNT=0

print_info "Checking backend health (port $BACKEND_PORT)..."
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s "http://localhost:$BACKEND_PORT/health" > /dev/null 2>&1; then
        HEALTH_RESPONSE=$(curl -s "http://localhost:$BACKEND_PORT/health")
        STATUS=$(echo "$HEALTH_RESPONSE" | grep -o '"status":"[^"]*"' | cut -d'"' -f4)
        if [ "$STATUS" = "healthy" ]; then
            print_success "Backend is healthy"
            break
        fi
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 1
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    print_error "Backend health check failed after $MAX_RETRIES seconds"
    docker compose logs omnimcp-backend --tail=20
    exit 1
fi

# OpenAPI health check
OPENAPI_PORT="${OPENAPI_PORT:-8006}"
print_info "Checking OpenAPI health (port $OPENAPI_PORT)..."
if curl -s "http://localhost:$OPENAPI_PORT/health" | grep -q "healthy"; then
    print_success "OpenAPI server is healthy"
else
    print_warning "OpenAPI server not responding (may still be starting)"
fi

# MCP health check
MCP_PORT="${MCP_PORT:-8007}"
print_info "Checking MCP health (port $MCP_PORT)..."
if curl -s "http://localhost:$MCP_PORT/health" | grep -q "healthy"; then
    print_success "MCP server is healthy"
else
    print_warning "MCP server not responding (may still be starting)"
fi

# Admin UI health check
ADMIN_PORT="${ADMIN_PORT:-3000}"
print_info "Checking Admin UI (port $ADMIN_PORT)..."
RETRY_COUNT=0
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s "http://localhost:$ADMIN_PORT" > /dev/null 2>&1; then
        print_success "Admin UI is accessible"
        break
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
    sleep 1
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
    print_warning "Admin UI not responding (container may still be starting)"
fi

# ==================================================
# Step 5: Run Unit Tests
# ==================================================

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

if [ $TEST_EXIT_CODE -eq 0 ]; then
    print_success "OmniMCP is ready!"
    exit 0
else
    print_warning "OmniMCP started with test failures"
    exit 1
fi

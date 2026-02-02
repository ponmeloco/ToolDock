#!/bin/bash
# ==================================================
# Test External MCP Server Integration for ToolDock
# ==================================================
#
# Prerequisites:
#   - ToolDock running (docker compose up -d)
#
# Usage: ./scripts/test_external_servers.sh
# ==================================================

set -e

# Get script directory and source .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Configuration
MCP_URL="${MCP_URL:-http://localhost:18007}"
WEB_URL="${WEB_URL:-http://localhost:18080}"
TOKEN="${BEARER_TOKEN:-change_me}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "========================================"
echo "  External MCP Server Integration Tests"
echo "========================================"
echo ""
echo "MCP URL: $MCP_URL"
echo "Web GUI URL: $WEB_URL"
echo ""

# Helper functions
pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    exit 1
}

warn() {
    echo -e "${YELLOW}! WARN${NC}: $1"
}

section() {
    echo ""
    echo -e "${BLUE}--- $1 ---${NC}"
}

# ==================================================
section "Test 1: Health Checks"
# ==================================================

MCP_HEALTH=$(curl -s "$MCP_URL/health")
if echo "$MCP_HEALTH" | grep -q '"status"'; then
    pass "MCP health check"
    echo "  Response: $MCP_HEALTH"
else
    fail "MCP health check failed"
fi

WEB_HEALTH=$(curl -s "$WEB_URL/health")
if echo "$WEB_HEALTH" | grep -q '"status"'; then
    pass "Web GUI health check"
    echo "  Response: $WEB_HEALTH"
else
    fail "Web GUI health check failed"
fi

# ==================================================
section "Test 2: List Namespaces"
# ==================================================

NAMESPACES=$(curl -s "$MCP_URL/mcp/namespaces" -H "Authorization: Bearer $TOKEN")
if echo "$NAMESPACES" | grep -q '\['; then
    pass "List namespaces"
    echo "  Namespaces: $NAMESPACES"
else
    fail "List namespaces failed"
fi

# ==================================================
section "Test 3: List External Servers (Web GUI API)"
# ==================================================

SERVERS=$(curl -s "$WEB_URL/api/servers" -H "Authorization: Bearer $TOKEN")
if echo "$SERVERS" | grep -q '"servers"'; then
    pass "List external servers"
    echo "  Response: $SERVERS"
else
    fail "List external servers failed"
fi

# ==================================================
section "Test 4: List Tools via MCP"
# ==================================================

MCP_TOOLS=$(curl -s -X POST "$MCP_URL/mcp/shared" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}')
if echo "$MCP_TOOLS" | grep -q '"tools"'; then
    pass "MCP tools/list (shared namespace)"
    TOOL_COUNT=$(echo "$MCP_TOOLS" | grep -o '"name"' | wc -l)
    echo "  Tool count: $TOOL_COUNT"
else
    fail "MCP tools/list failed"
fi

# ==================================================
section "Test 5: Global MCP tools/list"
# ==================================================

GLOBAL_TOOLS=$(curl -s -X POST "$MCP_URL/mcp" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}')
if echo "$GLOBAL_TOOLS" | grep -q '"tools"'; then
    pass "MCP tools/list (global)"
    TOOL_COUNT=$(echo "$GLOBAL_TOOLS" | grep -o '"name"' | wc -l)
    echo "  Tool count: $TOOL_COUNT"
else
    fail "MCP tools/list (global) failed"
fi

# ==================================================
section "Test 6: List Folders (Web GUI API)"
# ==================================================

FOLDERS=$(curl -s "$WEB_URL/api/folders" -H "Authorization: Bearer $TOKEN")
if echo "$FOLDERS" | grep -q '"folders"'; then
    pass "List folders"
    echo "  Response: $FOLDERS"
else
    fail "List folders failed"
fi

# ==================================================
section "Test 7: List Tools in Folder (Web GUI API)"
# ==================================================

FOLDER_TOOLS=$(curl -s "$WEB_URL/api/folders/shared/tools" -H "Authorization: Bearer $TOKEN")
if echo "$FOLDER_TOOLS" | grep -q '"tools"'; then
    pass "List tools in shared folder"
    echo "  Response: $FOLDER_TOOLS"
else
    fail "List tools in shared folder failed"
fi

# ==================================================
section "Test 8: Namespace Info"
# ==================================================

NS_INFO=$(curl -s "$MCP_URL/mcp/shared" -H "Authorization: Bearer $TOKEN")
if echo "$NS_INFO" | grep -q 'shared'; then
    pass "Namespace info"
    echo "  Response: $NS_INFO"
else
    fail "Namespace info failed"
fi

# ==================================================
section "Test 9: Invalid Namespace (should fail)"
# ==================================================

INVALID=$(curl -s -X POST "$MCP_URL/mcp/nonexistent" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}')
if echo "$INVALID" | grep -q 'error\|Unknown namespace'; then
    pass "Invalid namespace returns error"
    echo "  Response: $INVALID"
else
    warn "Invalid namespace did not return expected error"
    echo "  Response: $INVALID"
fi

# ==================================================
section "Test 10: Auth Required Check"
# ==================================================

NO_AUTH=$(curl -s "$MCP_URL/mcp/namespaces")
if echo "$NO_AUTH" | grep -q '401\|Unauthorized\|Authorization'; then
    pass "Auth required for namespaces endpoint"
else
    warn "Endpoint may not require auth (check BEARER_TOKEN config)"
fi

# ==================================================
echo ""
echo "========================================"
echo "  All Tests Complete"
echo "========================================"
echo ""
echo "Summary:"
echo "  - MCP Namespaces: $NAMESPACES"
echo "  - External Servers: configured via tooldock_data/external/config.yaml"
echo ""
echo "To add an external server, edit the config file and restart:"
echo "  nano tooldock_data/external/config.yaml"
echo "  docker compose restart"
echo ""

#!/bin/bash
# Test External MCP Server Integration for OmniMCP
#
# Prerequisites:
# - OmniMCP running (SERVER_MODE=both python main.py)
# - BEARER_TOKEN set or using default 'change_me'
#
# Usage: ./scripts/test_external_servers.sh

set -e

# Configuration
OPENAPI_URL="${OPENAPI_URL:-http://localhost:8006}"
MCP_URL="${MCP_URL:-http://localhost:8007}"
TOKEN="${BEARER_TOKEN:-change_me}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "  External MCP Server Integration Tests"
echo "========================================"
echo ""
echo "OpenAPI URL: $OPENAPI_URL"
echo "MCP URL: $MCP_URL"
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

# Test 1: Health Check
echo "--- Test 1: Health Checks ---"

OPENAPI_HEALTH=$(curl -s "$OPENAPI_URL/health")
if echo "$OPENAPI_HEALTH" | grep -q '"status"'; then
    pass "OpenAPI health check"
    echo "  Response: $OPENAPI_HEALTH"
else
    fail "OpenAPI health check failed"
fi

MCP_HEALTH=$(curl -s "$MCP_URL/health")
if echo "$MCP_HEALTH" | grep -q '"status"'; then
    pass "MCP health check"
    echo "  Response: $MCP_HEALTH"
else
    fail "MCP health check failed"
fi

echo ""

# Test 2: Admin Stats
echo "--- Test 2: Admin Stats ---"

STATS=$(curl -s "$OPENAPI_URL/admin/stats" -H "Authorization: Bearer $TOKEN")
if echo "$STATS" | grep -q '"tools"'; then
    pass "Admin stats endpoint"
    echo "  Response: $STATS"
else
    fail "Admin stats endpoint failed"
fi

echo ""

# Test 3: Search Registry
echo "--- Test 3: Search MCP Registry ---"

SEARCH=$(curl -s "$OPENAPI_URL/admin/servers/search?query=filesystem&limit=3" \
    -H "Authorization: Bearer $TOKEN")
if echo "$SEARCH" | grep -q 'name'; then
    pass "Registry search"
    echo "  Found servers in registry"
else
    warn "Registry search returned no results (might be network issue)"
fi

echo ""

# Test 4: List Installed Servers
echo "--- Test 4: List Installed Servers ---"

INSTALLED=$(curl -s "$OPENAPI_URL/admin/servers/installed" \
    -H "Authorization: Bearer $TOKEN")
if echo "$INSTALLED" | grep -q '\['; then
    pass "List installed servers"
    echo "  Response: $INSTALLED"
else
    fail "List installed servers failed"
fi

echo ""

# Test 5: List All Tools (via Admin API)
echo "--- Test 5: List All Tools ---"

TOOLS=$(curl -s "$OPENAPI_URL/admin/tools" -H "Authorization: Bearer $TOKEN")
if echo "$TOOLS" | grep -q '"native"'; then
    pass "List all tools"
    NATIVE=$(echo "$TOOLS" | grep -o '"native"[^}]*"count":[0-9]*' | grep -o '[0-9]*$')
    EXTERNAL=$(echo "$TOOLS" | grep -o '"external"[^}]*"count":[0-9]*' | grep -o '[0-9]*$')
    TOTAL=$(echo "$TOOLS" | grep -o '"total":[0-9]*' | grep -o '[0-9]*$')
    echo "  Native: ${NATIVE:-0}, External: ${EXTERNAL:-0}, Total: ${TOTAL:-0}"
else
    fail "List all tools failed"
fi

echo ""

# Test 6: Tools via OpenAPI
echo "--- Test 6: Tools via OpenAPI /tools ---"

OPENAPI_TOOLS=$(curl -s "$OPENAPI_URL/tools" -H "Authorization: Bearer $TOKEN")
if echo "$OPENAPI_TOOLS" | grep -q '"tools"'; then
    pass "OpenAPI /tools endpoint"
    TOOL_COUNT=$(echo "$OPENAPI_TOOLS" | grep -o '"name"' | wc -l)
    echo "  Tool count: $TOOL_COUNT"
else
    fail "OpenAPI /tools endpoint failed"
fi

echo ""

# Test 7: Tools via MCP
echo "--- Test 7: Tools via MCP ---"

MCP_TOOLS=$(curl -s -X POST "$MCP_URL/mcp" \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}')
if echo "$MCP_TOOLS" | grep -q '"tools"'; then
    pass "MCP tools/list"
    TOOL_COUNT=$(echo "$MCP_TOOLS" | grep -o '"name"' | wc -l)
    echo "  Tool count: $TOOL_COUNT"
else
    fail "MCP tools/list failed"
fi

echo ""

# Test 8: Add Server (Optional - only if npx available)
echo "--- Test 8: Add External Server (Optional) ---"

if command -v npx &> /dev/null; then
    # Try to add a simple test server
    ADD_RESULT=$(curl -s -X POST "$OPENAPI_URL/admin/servers/add" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{
            "server_id": "test-fs",
            "source": "custom",
            "command": "npx",
            "args": ["-y", "@anthropic/mcp-server-filesystem", "/tmp"],
            "save_to_config": false
        }' 2>/dev/null || echo '{"error": "failed"}')

    if echo "$ADD_RESULT" | grep -q '"status".*"connected"'; then
        pass "Add external server"
        echo "  Server 'test-fs' added successfully"

        # Test 9: Remove Server
        echo ""
        echo "--- Test 9: Remove External Server ---"

        REMOVE_RESULT=$(curl -s -X DELETE "$OPENAPI_URL/admin/servers/test-fs?remove_from_config=false" \
            -H "Authorization: Bearer $TOKEN")
        if echo "$REMOVE_RESULT" | grep -q '"removed"'; then
            pass "Remove external server"
        else
            warn "Remove server returned unexpected result"
        fi
    else
        warn "Could not add external server (might need npm/npx)"
        echo "  Result: $ADD_RESULT"
    fi
else
    warn "npx not available, skipping add/remove server tests"
fi

echo ""
echo "========================================"
echo "  Tests Complete"
echo "========================================"

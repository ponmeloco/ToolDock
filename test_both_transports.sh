#!/bin/bash

# ==================================================
# ToolDock - Test Script for All Transports
# ==================================================
#
# Tests all transports through the single Admin gateway port
#
# Usage: ./test_both_transports.sh
#
# Prerequisites:
#   - ToolDock running (docker compose up -d)
#   - curl installed
#   - jq installed (optional, for pretty output)
# ==================================================

set -e

# Get script directory and source .env
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

ADMIN_PORT=${ADMIN_PORT:-13000}
ADMIN_URL="http://localhost:${ADMIN_PORT}"
BEARER_TOKEN=${BEARER_TOKEN:-change_me_to_a_secure_token}
MCP_PROTOCOL_VERSION=${MCP_PROTOCOL_VERSION:-2025-11-25}
FAILURES=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=============================================="
echo "  ToolDock - Testing All Transports"
echo "=============================================="
echo ""
echo "Gateway URL:     $ADMIN_URL"
echo "Admin UI Port:   $ADMIN_PORT"
echo ""

# Check if jq is available
if command -v jq &> /dev/null; then
    JQ="jq ."
else
    JQ="cat"
    echo -e "${YELLOW}Note: Install jq for pretty-printed JSON output${NC}"
    echo ""
fi

# Helper functions
pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1"
}

fail() {
    echo -e "${RED}✗ FAIL${NC}: $1"
    FAILURES=$((FAILURES + 1))
}

section() {
    echo ""
    echo -e "${BLUE}==============================================
  $1
==============================================${NC}"
    echo ""
}

# ==================================================
section "1. Health Checks (No Auth Required, via gateway)"
# ==================================================

echo ">>> Tool API Health:"
OPENAPI_HEALTH=$(curl -s "$ADMIN_URL/openapi/health")
echo "$OPENAPI_HEALTH" | $JQ
if echo "$OPENAPI_HEALTH" | grep -q '"status"'; then
    pass "Tool API health check"
else
    fail "Tool API health check"
fi
echo ""

echo ">>> MCP Health:"
MCP_HEALTH=$(curl -s "$ADMIN_URL/mcp/health")
echo "$MCP_HEALTH" | $JQ
if echo "$MCP_HEALTH" | grep -q '"status"'; then
    pass "MCP health check"
else
    fail "MCP health check"
fi
echo ""

echo ">>> Backend API Health:"
WEB_HEALTH=$(curl -s "$ADMIN_URL/health")
echo "$WEB_HEALTH" | $JQ
if echo "$WEB_HEALTH" | grep -q '"status"'; then
    pass "Backend API health check"
else
    fail "Backend API health check"
fi

# ==================================================
section "2. Tool API (OpenAPI transport via gateway)"
# ==================================================

echo ">>> List Tools:"
TOOLS=$(curl -s "$ADMIN_URL/openapi/tools" \
  -H "Authorization: Bearer $BEARER_TOKEN")
echo "$TOOLS" | $JQ
if echo "$TOOLS" | grep -q '"tools"'; then
    pass "OpenAPI list tools"
else
    fail "OpenAPI list tools"
fi
echo ""

echo ">>> Call hello_world tool:"
RESULT=$(curl -s -X POST "$ADMIN_URL/openapi/tools/hello_world" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "OpenAPI Test"}')
echo "$RESULT" | $JQ
if echo "$RESULT" | grep -q 'Hello'; then
    pass "OpenAPI tool call"
else
    fail "OpenAPI tool call"
fi

# ==================================================
section "3. MCP Transport (via gateway)"
# ==================================================

echo ">>> List Namespaces:"
NAMESPACES=$(curl -s "$ADMIN_URL/mcp/namespaces" \
  -H "Authorization: Bearer $BEARER_TOKEN")
echo "$NAMESPACES" | $JQ
if echo "$NAMESPACES" | grep -q 'shared'; then
    pass "MCP list namespaces"
else
    fail "MCP list namespaces"
fi
echo ""

echo ">>> Server Info (GET /mcp/info):"
SERVER_INFO=$(curl -s "$ADMIN_URL/mcp/info" \
  -H "Authorization: Bearer $BEARER_TOKEN")
echo "$SERVER_INFO" | $JQ
if echo "$SERVER_INFO" | grep -q 'tooldock'; then
    pass "MCP server info"
else
    fail "MCP server info"
fi
echo ""

echo ">>> MCP Initialize:"
INIT=$(curl -s -X POST "$ADMIN_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "'"$MCP_PROTOCOL_VERSION"'",
      "capabilities": {},
      "clientInfo": {
        "name": "test-client",
        "version": "1.0.0"
      }
    }
  }')
echo "$INIT" | $JQ
if echo "$INIT" | grep -q '"protocolVersion"'; then
    pass "MCP initialize"
else
    fail "MCP initialize"
fi
echo ""

echo ">>> MCP List Tools (namespace: shared):"
MCP_TOOLS=$(curl -s -X POST "$ADMIN_URL/mcp/shared" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
  }')
echo "$MCP_TOOLS" | $JQ
if echo "$MCP_TOOLS" | grep -q '"tools"'; then
    pass "MCP list tools (shared namespace)"
else
    fail "MCP list tools (shared namespace)"
fi
echo ""

echo ">>> MCP Call hello_world tool (namespace: shared):"
MCP_CALL=$(curl -s -X POST "$ADMIN_URL/mcp/shared" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "hello_world",
      "arguments": {
        "name": "MCP Test"
      }
    }
  }')
echo "$MCP_CALL" | $JQ
if echo "$MCP_CALL" | grep -q 'Hello'; then
    pass "MCP tool call (shared namespace)"
else
    fail "MCP tool call (shared namespace)"
fi
echo ""

echo ">>> MCP Ping:"
PING=$(curl -s -X POST "$ADMIN_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "ping",
    "params": {}
  }')
echo "$PING" | $JQ
if echo "$PING" | grep -q '"result"'; then
    pass "MCP ping"
else
    fail "MCP ping"
fi

# ==================================================
section "4. Backend API (via gateway)"
# ==================================================

echo ">>> Dashboard API:"
DASHBOARD=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "$ADMIN_URL/api/dashboard")
echo "$DASHBOARD" | $JQ
if echo "$DASHBOARD" | grep -q '"server_name"'; then
    pass "Backend API dashboard"
else
    fail "Backend API dashboard"
fi
echo ""

echo ">>> List Folders:"
FOLDERS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "$ADMIN_URL/api/folders")
echo "$FOLDERS" | $JQ
if echo "$FOLDERS" | grep -q '"folders"'; then
    pass "Backend API list folders"
else
    fail "Backend API list folders"
fi
echo ""

echo ">>> List Tools in 'shared' folder:"
FOLDER_TOOLS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "$ADMIN_URL/api/folders/shared/tools")
echo "$FOLDER_TOOLS" | $JQ
if echo "$FOLDER_TOOLS" | grep -q '"tools"'; then
    pass "Backend API list tools in shared"
else
    fail "Backend API list tools in shared"
fi
echo ""

echo ">>> List MCP Servers:"
SERVERS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "$ADMIN_URL/api/fastmcp/servers")
echo "$SERVERS" | $JQ
if echo "$SERVERS" | grep -q '\['; then
    pass "Backend API list MCP servers"
else
    fail "Backend API list MCP servers"
fi
echo ""

echo ">>> Reload Status:"
RELOAD_STATUS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "$ADMIN_URL/api/reload/status")
echo "$RELOAD_STATUS" | $JQ
if echo "$RELOAD_STATUS" | grep -q '"enabled"'; then
    pass "Backend API reload status"
else
    fail "Backend API reload status"
fi

# ==================================================
section "5. Test Summary"
# ==================================================

echo ""
echo "All tests completed!"
echo ""
echo "Access points:"
echo "  - Admin UI:    $ADMIN_URL"
echo "  - Tool API:    $ADMIN_URL/openapi"
echo "  - MCP HTTP:    $ADMIN_URL/mcp"
echo "  - Backend API: $ADMIN_URL/api"
echo ""
echo "MCP Endpoints for LiteLLM:"
echo "  - $ADMIN_URL/mcp/shared"
echo ""

if [ "$FAILURES" -gt 0 ]; then
    echo -e "${RED}Test result: $FAILURES failure(s)${NC}"
    exit 1
fi

echo -e "${GREEN}Test result: all checks passed${NC}"

#!/bin/bash

# ==================================================
# OmniMCP - Test Script for All Transports
# ==================================================
#
# Tests all three servers: OpenAPI, MCP HTTP, and Backend API
#
# Usage: ./test_both_transports.sh
#
# Prerequisites:
#   - OmniMCP running (docker compose up -d)
#   - curl installed
#   - jq installed (optional, for pretty output)
# ==================================================

set -e

OPENAPI_PORT=${OPENAPI_PORT:-8006}
MCP_PORT=${MCP_PORT:-8007}
WEB_PORT=${WEB_PORT:-8080}
ADMIN_PORT=${ADMIN_PORT:-3000}
BEARER_TOKEN=${BEARER_TOKEN:-change_me}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=============================================="
echo "  OmniMCP - Testing All Transports"
echo "=============================================="
echo ""
echo "OpenAPI Port:    $OPENAPI_PORT"
echo "MCP Port:        $MCP_PORT"
echo "Backend API:     $WEB_PORT"
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
}

section() {
    echo ""
    echo -e "${BLUE}==============================================
  $1
==============================================${NC}"
    echo ""
}

# ==================================================
section "1. Health Checks (No Auth Required)"
# ==================================================

echo ">>> OpenAPI Health:"
OPENAPI_HEALTH=$(curl -s "http://localhost:$OPENAPI_PORT/health")
echo "$OPENAPI_HEALTH" | $JQ
if echo "$OPENAPI_HEALTH" | grep -q '"status"'; then
    pass "OpenAPI health check"
else
    fail "OpenAPI health check"
fi
echo ""

echo ">>> MCP Health:"
MCP_HEALTH=$(curl -s "http://localhost:$MCP_PORT/health")
echo "$MCP_HEALTH" | $JQ
if echo "$MCP_HEALTH" | grep -q '"status"'; then
    pass "MCP health check"
else
    fail "MCP health check"
fi
echo ""

echo ">>> Backend API Health:"
WEB_HEALTH=$(curl -s "http://localhost:$WEB_PORT/health")
echo "$WEB_HEALTH" | $JQ
if echo "$WEB_HEALTH" | grep -q '"status"'; then
    pass "Backend API health check"
else
    fail "Backend API health check"
fi

# ==================================================
section "2. OpenAPI Server (Port $OPENAPI_PORT)"
# ==================================================

echo ">>> List Tools:"
TOOLS=$(curl -s "http://localhost:$OPENAPI_PORT/tools" \
  -H "Authorization: Bearer $BEARER_TOKEN")
echo "$TOOLS" | $JQ
if echo "$TOOLS" | grep -q '"tools"'; then
    pass "OpenAPI list tools"
else
    fail "OpenAPI list tools"
fi
echo ""

echo ">>> Call hello_world tool:"
RESULT=$(curl -s -X POST "http://localhost:$OPENAPI_PORT/tools/hello_world" \
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
section "3. MCP Server (Port $MCP_PORT)"
# ==================================================

echo ">>> List Namespaces:"
NAMESPACES=$(curl -s "http://localhost:$MCP_PORT/mcp/namespaces" \
  -H "Authorization: Bearer $BEARER_TOKEN")
echo "$NAMESPACES" | $JQ
if echo "$NAMESPACES" | grep -q 'shared'; then
    pass "MCP list namespaces"
else
    fail "MCP list namespaces"
fi
echo ""

echo ">>> Server Info (GET /mcp):"
SERVER_INFO=$(curl -s "http://localhost:$MCP_PORT/mcp" \
  -H "Authorization: Bearer $BEARER_TOKEN")
echo "$SERVER_INFO" | $JQ
if echo "$SERVER_INFO" | grep -q 'omnimcp'; then
    pass "MCP server info"
else
    fail "MCP server info"
fi
echo ""

echo ">>> MCP Initialize:"
INIT=$(curl -s -X POST "http://localhost:$MCP_PORT/mcp" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
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
MCP_TOOLS=$(curl -s -X POST "http://localhost:$MCP_PORT/mcp/shared" \
  -H "Content-Type: application/json" \
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
MCP_CALL=$(curl -s -X POST "http://localhost:$MCP_PORT/mcp/shared" \
  -H "Content-Type: application/json" \
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
PING=$(curl -s -X POST "http://localhost:$MCP_PORT/mcp" \
  -H "Content-Type: application/json" \
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
section "4. Backend API (Port $WEB_PORT)"
# ==================================================

echo ">>> Dashboard API:"
DASHBOARD=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/dashboard")
echo "$DASHBOARD" | $JQ
if echo "$DASHBOARD" | grep -q '"server_name"'; then
    pass "Backend API dashboard"
else
    fail "Backend API dashboard"
fi
echo ""

echo ">>> List Folders:"
FOLDERS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/folders")
echo "$FOLDERS" | $JQ
if echo "$FOLDERS" | grep -q '"folders"'; then
    pass "Backend API list folders"
else
    fail "Backend API list folders"
fi
echo ""

echo ">>> List Tools in 'shared' folder:"
FOLDER_TOOLS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/folders/shared/tools")
echo "$FOLDER_TOOLS" | $JQ
if echo "$FOLDER_TOOLS" | grep -q '"tools"'; then
    pass "Backend API list tools in shared"
else
    fail "Backend API list tools in shared"
fi
echo ""

echo ">>> List External Servers:"
SERVERS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/servers")
echo "$SERVERS" | $JQ
if echo "$SERVERS" | grep -q '"servers"'; then
    pass "Backend API list servers"
else
    fail "Backend API list servers"
fi
echo ""

echo ">>> Reload Status:"
RELOAD_STATUS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/reload/status")
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
echo "  - OpenAPI:     http://localhost:$OPENAPI_PORT"
echo "  - MCP HTTP:    http://localhost:$MCP_PORT"
echo "  - Backend API: http://localhost:$WEB_PORT"
echo "  - Admin UI:    http://localhost:$ADMIN_PORT"
echo ""
echo "MCP Endpoints for LiteLLM:"
echo "  - http://localhost:$MCP_PORT/mcp/shared"
echo ""

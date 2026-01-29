#!/bin/bash

# ==================================================
# OmniMCP - Test Script for All Transports
# ==================================================
#
# Tests all three servers: OpenAPI, MCP HTTP, and Web GUI
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
BEARER_TOKEN=${BEARER_TOKEN:-change_me}
ADMIN_USER=${ADMIN_USERNAME:-admin}

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
echo "OpenAPI Port: $OPENAPI_PORT"
echo "MCP Port:     $MCP_PORT"
echo "Web GUI Port: $WEB_PORT"
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

echo ">>> Web GUI Health:"
WEB_HEALTH=$(curl -s "http://localhost:$WEB_PORT/health")
echo "$WEB_HEALTH" | $JQ
if echo "$WEB_HEALTH" | grep -q '"status"'; then
    pass "Web GUI health check"
else
    fail "Web GUI health check"
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
section "4. Web GUI (Port $WEB_PORT)"
# ==================================================

echo ">>> Dashboard API (Basic Auth):"
DASHBOARD=$(curl -s -u "$ADMIN_USER:$BEARER_TOKEN" "http://localhost:$WEB_PORT/api/dashboard")
echo "$DASHBOARD" | $JQ
if echo "$DASHBOARD" | grep -q '"server_name"'; then
    pass "Web GUI dashboard API (Basic Auth)"
else
    fail "Web GUI dashboard API (Basic Auth)"
fi
echo ""

echo ">>> Dashboard API (Bearer Token):"
DASHBOARD2=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/dashboard")
echo "$DASHBOARD2" | $JQ
if echo "$DASHBOARD2" | grep -q '"server_name"'; then
    pass "Web GUI dashboard API (Bearer Token)"
else
    fail "Web GUI dashboard API (Bearer Token)"
fi
echo ""

echo ">>> List Folders:"
FOLDERS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/folders")
echo "$FOLDERS" | $JQ
if echo "$FOLDERS" | grep -q '"folders"'; then
    pass "Web GUI list folders"
else
    fail "Web GUI list folders"
fi
echo ""

echo ">>> List Tools in 'shared' folder:"
FOLDER_TOOLS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/folders/shared/tools")
echo "$FOLDER_TOOLS" | $JQ
if echo "$FOLDER_TOOLS" | grep -q '"tools"'; then
    pass "Web GUI list tools in shared"
else
    fail "Web GUI list tools in shared"
fi
echo ""

echo ">>> List External Servers:"
SERVERS=$(curl -s -H "Authorization: Bearer $BEARER_TOKEN" "http://localhost:$WEB_PORT/api/servers")
echo "$SERVERS" | $JQ
if echo "$SERVERS" | grep -q '"servers"'; then
    pass "Web GUI list servers"
else
    fail "Web GUI list servers"
fi

# ==================================================
section "5. Test Summary"
# ==================================================

echo ""
echo "All tests completed!"
echo ""
echo "Access points:"
echo "  - OpenAPI:  http://localhost:$OPENAPI_PORT"
echo "  - MCP HTTP: http://localhost:$MCP_PORT"
echo "  - Web GUI:  http://localhost:$WEB_PORT (user: $ADMIN_USER)"
echo ""
echo "MCP Endpoints for LiteLLM:"
echo "  - http://localhost:$MCP_PORT/mcp/shared"
echo ""

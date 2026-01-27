#!/bin/bash

# Test script for both OpenAPI and MCP transports
# Run with: ./test_both_transports.sh

set -e

OPENAPI_PORT=${OPENAPI_PORT:-8006}
MCP_PORT=${MCP_PORT:-8007}
BEARER_TOKEN=${BEARER_TOKEN:-change_me_openapi}

echo "=============================================="
echo "  Testing Both Transports"
echo "=============================================="
echo ""
echo "OpenAPI Port: $OPENAPI_PORT"
echo "MCP Port: $MCP_PORT"
echo ""

# Check if jq is available
if command -v jq &> /dev/null; then
    JQ="jq ."
else
    JQ="cat"
    echo "Note: Install jq for pretty-printed JSON output"
    echo ""
fi

echo "=============================================="
echo "  1. Testing OpenAPI Server (Port $OPENAPI_PORT)"
echo "=============================================="
echo ""

# Health Check
echo ">>> Health Check:"
curl -s "http://localhost:$OPENAPI_PORT/health" | $JQ
echo ""

# List Tools (with auth)
echo ">>> List Tools:"
curl -s "http://localhost:$OPENAPI_PORT/tools" \
  -H "Authorization: Bearer $BEARER_TOKEN" | $JQ
echo ""

# Call hello_world tool
echo ">>> Call hello_world tool:"
curl -s -X POST "http://localhost:$OPENAPI_PORT/tools/hello_world" \
  -H "Authorization: Bearer $BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "OpenAPI Test"}' | $JQ
echo ""

echo "=============================================="
echo "  2. Testing MCP Server (Port $MCP_PORT)"
echo "=============================================="
echo ""

# Health Check
echo ">>> Health Check:"
curl -s "http://localhost:$MCP_PORT/health" | $JQ
echo ""

# Server Info (GET /mcp)
echo ">>> Server Info:"
curl -s "http://localhost:$MCP_PORT/mcp" | $JQ
echo ""

# MCP Initialize
echo ">>> MCP Initialize:"
curl -s -X POST "http://localhost:$MCP_PORT/mcp" \
  -H "Content-Type: application/json" \
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
  }' | $JQ
echo ""

# MCP List Tools
echo ">>> MCP List Tools:"
curl -s -X POST "http://localhost:$MCP_PORT/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
  }' | $JQ
echo ""

# MCP Call Tool
echo ">>> MCP Call hello_world tool:"
curl -s -X POST "http://localhost:$MCP_PORT/mcp" \
  -H "Content-Type: application/json" \
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
  }' | $JQ
echo ""

# MCP Ping
echo ">>> MCP Ping:"
curl -s -X POST "http://localhost:$MCP_PORT/mcp" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "ping",
    "params": {}
  }' | $JQ
echo ""

echo "=============================================="
echo "  All Tests Complete!"
echo "=============================================="

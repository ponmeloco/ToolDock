import { useState, useEffect } from 'react'
import { Key, Send, ChevronDown, ChevronRight, Check, Copy, ExternalLink } from 'lucide-react'
import CodeMirror from '@uiw/react-codemirror'
import { json } from '@codemirror/lang-json'

interface Endpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  description: string
  auth: boolean
  body?: string
}

interface EndpointCategory {
  name: string
  description: string
  endpoints: Endpoint[]
}

const CATEGORIES: EndpointCategory[] = [
  {
    name: 'Health',
    description: 'Health check endpoints for all services',
    endpoints: [
      { method: 'GET', path: '/health', description: 'Backend API health check', auth: false },
      { method: 'GET', path: '/api/admin/health', description: 'Aggregated health of all services', auth: true },
    ],
  },
  {
    name: 'Namespaces',
    description: 'Manage tool namespaces (folders)',
    endpoints: [
      { method: 'GET', path: '/api/folders', description: 'List all namespaces', auth: true },
      { method: 'POST', path: '/api/folders', description: 'Create a new namespace', auth: true, body: '{"name": "my_namespace"}' },
      { method: 'DELETE', path: '/api/folders/shared', description: 'Delete a namespace', auth: true },
    ],
  },
  {
    name: 'Tools',
    description: 'Manage tools within namespaces',
    endpoints: [
      { method: 'GET', path: '/api/folders/shared/tools', description: 'List tools in a namespace', auth: true },
      { method: 'GET', path: '/api/folders/shared/tools/example.py', description: 'Get tool content', auth: true },
      { method: 'POST', path: '/api/folders/shared/tools/create-from-template', description: 'Create tool from template', auth: true, body: '{"name": "my_tool"}' },
      { method: 'PUT', path: '/api/folders/shared/tools/example.py', description: 'Update tool content', auth: true, body: '{"content": "# Updated content"}' },
    ],
  },
  {
    name: 'Reload',
    description: 'Hot reload tools without server restart',
    endpoints: [
      { method: 'GET', path: '/api/reload/status', description: 'Get reload status and namespaces', auth: true },
      { method: 'POST', path: '/api/reload', description: 'Reload all namespaces', auth: true },
      { method: 'POST', path: '/api/reload/shared', description: 'Reload specific namespace', auth: true },
    ],
  },
  {
    name: 'OpenAPI Tools',
    description: 'Execute tools via OpenAPI (port 8006)',
    endpoints: [
      { method: 'GET', path: '/tools', description: 'List all available tools', auth: true },
      { method: 'POST', path: '/tools/hello_world', description: 'Execute hello_world tool', auth: true, body: '{"name": "World"}' },
    ],
  },
  {
    name: 'Admin',
    description: 'System administration endpoints',
    endpoints: [
      { method: 'GET', path: '/api/admin/info', description: 'System information', auth: true },
      { method: 'GET', path: '/api/admin/logs?limit=20', description: 'Get recent logs', auth: true },
      { method: 'GET', path: '/api/servers', description: 'List external MCP servers', auth: true },
    ],
  },
  {
    name: 'MCP',
    description: 'MCP protocol endpoints (port 8007)',
    endpoints: [
      { method: 'GET', path: '/mcp/namespaces', description: 'List MCP namespaces', auth: true },
      { method: 'GET', path: '/mcp/shared', description: 'Namespace info', auth: true },
      { method: 'POST', path: '/mcp/shared', description: 'MCP tools/list', auth: true, body: '{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}' },
      { method: 'POST', path: '/mcp/shared', description: 'MCP tools/call (hello_world)', auth: true, body: '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "hello_world", "arguments": {"name": "World"}}}' },
    ],
  },
]

function getMethodColor(method: string): string {
  switch (method) {
    case 'GET': return 'bg-green-100 text-green-700 border-green-200'
    case 'POST': return 'bg-blue-100 text-blue-700 border-blue-200'
    case 'PUT': return 'bg-yellow-100 text-yellow-700 border-yellow-200'
    case 'DELETE': return 'bg-red-100 text-red-700 border-red-200'
    default: return 'bg-gray-100 text-gray-700 border-gray-200'
  }
}

function getStatusColor(status: number): string {
  if (status >= 200 && status < 300) return 'text-green-600'
  if (status >= 400 && status < 500) return 'text-yellow-600'
  if (status >= 500) return 'text-red-600'
  return 'text-gray-600'
}

export default function Docs() {
  const [token, setToken] = useState('')
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['Health', 'OpenAPI Tools']))
  const [activeEndpoint, setActiveEndpoint] = useState<{ category: string; endpoint: Endpoint } | null>(null)
  const [requestBody, setRequestBody] = useState('')
  const [response, setResponse] = useState<{ status: number; data: string; time: number } | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  // Load token from localStorage on mount
  useEffect(() => {
    const savedToken = localStorage.getItem('omnimcp_token') || ''
    setToken(savedToken)
  }, [])

  // Save token to localStorage when changed
  const handleTokenChange = (newToken: string) => {
    setToken(newToken)
    if (newToken) {
      localStorage.setItem('omnimcp_token', newToken)
    } else {
      localStorage.removeItem('omnimcp_token')
    }
  }

  const toggleCategory = (category: string) => {
    const newExpanded = new Set(expandedCategories)
    if (newExpanded.has(category)) {
      newExpanded.delete(category)
    } else {
      newExpanded.add(category)
    }
    setExpandedCategories(newExpanded)
  }

  const selectEndpoint = (category: string, endpoint: Endpoint) => {
    setActiveEndpoint({ category, endpoint })
    setRequestBody(endpoint.body || '')
    setResponse(null)
  }

  const executeRequest = async () => {
    if (!activeEndpoint) return

    setIsLoading(true)
    setResponse(null)

    const startTime = Date.now()
    const endpoint = activeEndpoint.endpoint

    try {
      // All requests go through nginx on current origin
      const url = endpoint.path

      const headers: Record<string, string> = {}
      if (endpoint.auth && token) {
        headers['Authorization'] = `Bearer ${token}`
      }
      if (requestBody && endpoint.method !== 'GET') {
        headers['Content-Type'] = 'application/json'
      }

      const options: RequestInit = {
        method: endpoint.method,
        headers,
      }

      if (requestBody && endpoint.method !== 'GET') {
        options.body = requestBody
      }

      const res = await fetch(url, options)
      const duration = Date.now() - startTime

      let data: string
      const contentType = res.headers.get('content-type')
      if (contentType?.includes('application/json')) {
        const jsonData = await res.json()
        data = JSON.stringify(jsonData, null, 2)
      } else {
        data = await res.text()
      }

      setResponse({ status: res.status, data, time: duration })
    } catch (error) {
      const duration = Date.now() - startTime
      setResponse({
        status: 0,
        data: JSON.stringify({ error: String(error) }, null, 2),
        time: duration
      })
    } finally {
      setIsLoading(false)
    }
  }

  const copyResponse = () => {
    if (response?.data) {
      navigator.clipboard.writeText(response.data)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const copyCurl = () => {
    if (!activeEndpoint) return

    const endpoint = activeEndpoint.endpoint
    const baseUrl = window.location.origin
    const url = `${baseUrl}${endpoint.path}`

    let curl = `curl -X ${endpoint.method} "${url}"`
    if (endpoint.auth && token) {
      curl += ` \\\n  -H "Authorization: Bearer ${token}"`
    }
    if (requestBody && endpoint.method !== 'GET') {
      curl += ` \\\n  -H "Content-Type: application/json"`
      curl += ` \\\n  -d '${requestBody}'`
    }

    navigator.clipboard.writeText(curl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">API Documentation</h1>
        <a
          href="/docs"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-2 px-3 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <ExternalLink className="w-4 h-4" />
          Swagger UI
        </a>
      </div>

      {/* Token Input */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 mb-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2 text-gray-600">
            <Key className="w-5 h-5" />
            <span className="font-medium">Bearer Token:</span>
          </div>
          <input
            type="password"
            value={token}
            onChange={(e) => handleTokenChange(e.target.value)}
            placeholder="Enter your bearer token..."
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none font-mono text-sm"
          />
          {token && (
            <span className="flex items-center gap-1 text-sm text-green-600">
              <Check className="w-4 h-4" />
              Token set
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 flex gap-4 min-h-0">
        {/* Endpoints List */}
        <div className="w-96 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
          <div className="p-3 border-b border-gray-200 bg-gray-50">
            <h2 className="font-semibold text-gray-700">Endpoints</h2>
          </div>
          <div className="flex-1 overflow-auto">
            {CATEGORIES.map((category) => (
              <div key={category.name}>
                <button
                  onClick={() => toggleCategory(category.name)}
                  className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 border-b border-gray-200 text-left"
                >
                  {expandedCategories.has(category.name) ? (
                    <ChevronDown className="w-4 h-4 text-gray-500" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-gray-500" />
                  )}
                  <div className="flex-1">
                    <span className="font-medium text-gray-700">{category.name}</span>
                    <p className="text-xs text-gray-500">{category.description}</p>
                  </div>
                  <span className="text-xs text-gray-500">{category.endpoints.length}</span>
                </button>
                {expandedCategories.has(category.name) && (
                  <div className="divide-y divide-gray-100">
                    {category.endpoints.map((endpoint, i) => (
                      <button
                        key={i}
                        onClick={() => selectEndpoint(category.name, endpoint)}
                        className={`w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 ${
                          activeEndpoint?.endpoint === endpoint ? 'bg-primary-50 border-l-2 border-primary-500' : ''
                        }`}
                      >
                        <span className={`px-1.5 py-0.5 text-xs font-bold rounded border ${getMethodColor(endpoint.method)}`}>
                          {endpoint.method}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span className="text-sm text-gray-600 truncate block" title={endpoint.path}>
                            {endpoint.path}
                          </span>
                          <span className="text-xs text-gray-400">{endpoint.description}</span>
                        </div>
                        {endpoint.auth && (
                          <span title="Auth required">
                            <Key className="w-3 h-3 text-gray-400" />
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Request/Response */}
        <div className="flex-1 flex flex-col gap-4 min-h-0">
          {activeEndpoint ? (
            <>
              {/* Request */}
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
                <div className="p-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={`px-2 py-1 text-sm font-bold rounded border ${getMethodColor(activeEndpoint.endpoint.method)}`}>
                      {activeEndpoint.endpoint.method}
                    </span>
                    <code className="text-sm text-gray-700">{activeEndpoint.endpoint.path}</code>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={copyCurl}
                      className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
                      title="Copy as cURL"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                    <button
                      onClick={executeRequest}
                      disabled={isLoading || (activeEndpoint.endpoint.auth && !token)}
                      className="flex items-center gap-2 px-4 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:bg-gray-300 text-white rounded-lg transition-colors"
                    >
                      <Send className="w-4 h-4" />
                      {isLoading ? 'Sending...' : 'Send'}
                    </button>
                  </div>
                </div>
                <div className="p-3">
                  <p className="text-sm text-gray-600 mb-2">{activeEndpoint.endpoint.description}</p>
                  {activeEndpoint.endpoint.auth && !token && (
                    <p className="text-sm text-yellow-600 mb-2">This endpoint requires authentication. Enter a token above.</p>
                  )}
                  {activeEndpoint.endpoint.body && (
                    <div className="mt-3">
                      <label className="block text-sm font-medium text-gray-700 mb-1">Request Body:</label>
                      <CodeMirror
                        value={requestBody}
                        height="100px"
                        extensions={[json()]}
                        onChange={(value) => setRequestBody(value)}
                        className="border border-gray-300 rounded-lg overflow-hidden"
                      />
                    </div>
                  )}
                </div>
              </div>

              {/* Response */}
              <div className="flex-1 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col min-h-0">
                <div className="p-3 border-b border-gray-200 bg-gray-50 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-gray-700">Response</span>
                    {response && (
                      <>
                        <span className={`font-bold ${getStatusColor(response.status)}`}>
                          {response.status || 'Error'}
                        </span>
                        <span className="text-sm text-gray-500">{response.time}ms</span>
                      </>
                    )}
                  </div>
                  {response && (
                    <button
                      onClick={copyResponse}
                      className="flex items-center gap-1 px-2 py-1 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded transition-colors"
                    >
                      {copied ? <Check className="w-4 h-4 text-green-600" /> : <Copy className="w-4 h-4" />}
                      {copied ? 'Copied!' : 'Copy'}
                    </button>
                  )}
                </div>
                <div className="flex-1 overflow-auto p-3">
                  {isLoading ? (
                    <div className="flex items-center justify-center h-full text-gray-500">
                      Loading...
                    </div>
                  ) : response ? (
                    <pre className="text-sm font-mono whitespace-pre-wrap text-gray-800">
                      {response.data}
                    </pre>
                  ) : (
                    <div className="flex items-center justify-center h-full text-gray-400">
                      Click "Send" to execute the request
                    </div>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 bg-white rounded-xl shadow-sm border border-gray-200 flex items-center justify-center text-gray-400">
              Select an endpoint from the list to test it
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

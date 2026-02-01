import { useState, useEffect } from 'react'
import { Key, Send, ChevronDown, ChevronRight, Check, Copy } from 'lucide-react'
import CodeMirror from '@uiw/react-codemirror'
import { json } from '@codemirror/lang-json'

interface Endpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  description: string
  auth: boolean
  body?: string
  category: string
}

const ENDPOINTS: Endpoint[] = [
  // Health
  { method: 'GET', path: '/health', description: 'Backend health check', auth: false, category: 'Health' },
  { method: 'GET', path: '/api/admin/health', description: 'System health (all services)', auth: true, category: 'Health' },

  // Namespaces & Tools
  { method: 'GET', path: '/api/folders', description: 'List all namespaces', auth: true, category: 'Namespaces' },
  { method: 'GET', path: '/api/folders/shared/tools', description: 'List tools in namespace', auth: true, category: 'Namespaces' },

  // Reload
  { method: 'POST', path: '/api/reload', description: 'Hot reload all namespaces', auth: true, category: 'Reload' },
  { method: 'POST', path: '/api/reload/shared', description: 'Hot reload specific namespace', auth: true, category: 'Reload' },
  { method: 'GET', path: '/api/reload/status', description: 'Get reload status', auth: true, category: 'Reload' },

  // Tools (OpenAPI)
  { method: 'GET', path: '/tools', description: 'List all tools (OpenAPI)', auth: true, category: 'OpenAPI' },
  { method: 'POST', path: '/tools/hello_world', description: 'Execute hello_world tool', auth: true, category: 'OpenAPI', body: '{"name": "World"}' },

  // Admin
  { method: 'GET', path: '/api/admin/info', description: 'System information', auth: true, category: 'Admin' },
  { method: 'GET', path: '/api/admin/logs?limit=10', description: 'Get recent logs', auth: true, category: 'Admin' },
  { method: 'GET', path: '/api/servers', description: 'List external servers', auth: true, category: 'Admin' },

  // MCP (Port 8007)
  { method: 'GET', path: 'http://localhost:8007/health', description: 'MCP health check', auth: false, category: 'MCP' },
  { method: 'GET', path: 'http://localhost:8007/mcp/namespaces', description: 'List MCP namespaces', auth: true, category: 'MCP' },
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
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set(['Health', 'OpenAPI']))
  const [activeEndpoint, setActiveEndpoint] = useState<Endpoint | null>(null)
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

  const selectEndpoint = (endpoint: Endpoint) => {
    setActiveEndpoint(endpoint)
    setRequestBody(endpoint.body || '')
    setResponse(null)
  }

  const executeRequest = async () => {
    if (!activeEndpoint) return

    setIsLoading(true)
    setResponse(null)

    const startTime = Date.now()

    try {
      const isExternalUrl = activeEndpoint.path.startsWith('http')
      const url = isExternalUrl ? activeEndpoint.path : activeEndpoint.path

      const headers: Record<string, string> = {}
      if (activeEndpoint.auth && token) {
        headers['Authorization'] = `Bearer ${token}`
      }
      if (requestBody && activeEndpoint.method !== 'GET') {
        headers['Content-Type'] = 'application/json'
      }

      const options: RequestInit = {
        method: activeEndpoint.method,
        headers,
      }

      if (requestBody && activeEndpoint.method !== 'GET') {
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

    const isExternalUrl = activeEndpoint.path.startsWith('http')
    const url = isExternalUrl ? activeEndpoint.path : `http://localhost:8080${activeEndpoint.path}`

    let curl = `curl -X ${activeEndpoint.method} "${url}"`
    if (activeEndpoint.auth && token) {
      curl += ` \\\n  -H "Authorization: Bearer ${token}"`
    }
    if (requestBody && activeEndpoint.method !== 'GET') {
      curl += ` \\\n  -H "Content-Type: application/json"`
      curl += ` \\\n  -d '${requestBody}'`
    }

    navigator.clipboard.writeText(curl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // Group endpoints by category
  const categories = ENDPOINTS.reduce((acc, endpoint) => {
    if (!acc[endpoint.category]) {
      acc[endpoint.category] = []
    }
    acc[endpoint.category].push(endpoint)
    return acc
  }, {} as Record<string, Endpoint[]>)

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">API Documentation</h1>
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
        <div className="w-80 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
          <div className="p-3 border-b border-gray-200 bg-gray-50">
            <h2 className="font-semibold text-gray-700">Endpoints</h2>
          </div>
          <div className="flex-1 overflow-auto">
            {Object.entries(categories).map(([category, endpoints]) => (
              <div key={category}>
                <button
                  onClick={() => toggleCategory(category)}
                  className="w-full flex items-center gap-2 px-3 py-2 bg-gray-50 hover:bg-gray-100 border-b border-gray-200 text-left"
                >
                  {expandedCategories.has(category) ? (
                    <ChevronDown className="w-4 h-4 text-gray-500" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-gray-500" />
                  )}
                  <span className="font-medium text-gray-700">{category}</span>
                  <span className="ml-auto text-xs text-gray-500">{endpoints.length}</span>
                </button>
                {expandedCategories.has(category) && (
                  <div className="divide-y divide-gray-100">
                    {endpoints.map((endpoint, i) => (
                      <button
                        key={i}
                        onClick={() => selectEndpoint(endpoint)}
                        className={`w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-gray-50 ${
                          activeEndpoint === endpoint ? 'bg-primary-50 border-l-2 border-primary-500' : ''
                        }`}
                      >
                        <span className={`px-1.5 py-0.5 text-xs font-bold rounded border ${getMethodColor(endpoint.method)}`}>
                          {endpoint.method}
                        </span>
                        <span className="text-sm text-gray-600 truncate flex-1" title={endpoint.path}>
                          {endpoint.path.replace('http://localhost:8007', '')}
                        </span>
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
                    <span className={`px-2 py-1 text-sm font-bold rounded border ${getMethodColor(activeEndpoint.method)}`}>
                      {activeEndpoint.method}
                    </span>
                    <code className="text-sm text-gray-700">{activeEndpoint.path}</code>
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
                      disabled={isLoading || (activeEndpoint.auth && !token)}
                      className="flex items-center gap-2 px-4 py-1.5 bg-primary-600 hover:bg-primary-700 disabled:bg-gray-300 text-white rounded-lg transition-colors"
                    >
                      <Send className="w-4 h-4" />
                      {isLoading ? 'Sending...' : 'Send'}
                    </button>
                  </div>
                </div>
                <div className="p-3">
                  <p className="text-sm text-gray-600 mb-2">{activeEndpoint.description}</p>
                  {activeEndpoint.auth && !token && (
                    <p className="text-sm text-yellow-600 mb-2">This endpoint requires authentication. Enter a token above.</p>
                  )}
                  {activeEndpoint.method !== 'GET' && activeEndpoint.body && (
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

import { useState, useEffect, useCallback, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Key, Send, ChevronDown, ChevronRight, Check, Copy, ExternalLink } from 'lucide-react'
import CodeMirror from '@uiw/react-codemirror'
import { json } from '@codemirror/lang-json'
import { getAllNamespaces, getAllTools, getTools, listFastMcpServers } from '../api/client'

interface PathParam {
  name: string
  description: string
  default?: string
}

interface Endpoint {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  description: string
  auth: boolean
  body?: string
  pathParams?: PathParam[]
  headers?: Record<string, string>
  note?: string
}

interface EndpointCategory {
  name: string
  description: string
  endpoints: Endpoint[]
  baseUrl?: string
}

interface PathParamOption {
  value: string
  label: string
}

const TOOL_API_CATEGORY = 'Tool API'
const MCP_TRANSPORT_CATEGORY = 'MCP Transport'

function buildCategories(): EndpointCategory[] {
  return [
    {
      name: 'Getting Started',
      description: 'Core health and system endpoints',
      endpoints: [
        { method: 'GET', path: '/health', description: 'Backend API health check', auth: false },
        { method: 'GET', path: '/api/dashboard', description: 'Dashboard overview', auth: true },
        { method: 'GET', path: '/api/admin/health', description: 'Aggregated health of all services', auth: true },
        { method: 'GET', path: '/api/admin/info', description: 'System information', auth: true },
        { method: 'GET', path: '/api/admin/metrics', description: 'Service/tool metrics', auth: true },
        { method: 'GET', path: '/api/admin/namespaces', description: 'Unified namespace list', auth: true },
        { method: 'GET', path: '/api/admin/logs?limit=20', description: 'Get recent logs', auth: true },
      ],
    },
    {
      name: 'Namespaces & Tools',
      description: 'Manage namespaces, tools, and per-namespace dependencies',
      endpoints: [
        { method: 'GET', path: '/api/folders', description: 'List all namespaces', auth: true },
        { method: 'POST', path: '/api/folders', description: 'Create a new namespace', auth: true, body: '{"name":"my_namespace"}' },
        {
          method: 'DELETE',
          path: '/api/folders/{namespace}',
          description: 'Delete a namespace',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace to delete' }],
        },
        {
          method: 'GET',
          path: '/api/folders/{namespace}/files',
          description: 'List tools in a namespace',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'GET',
          path: '/api/folders/{namespace}/files/{filename}',
          description: 'Get tool content',
          auth: true,
          pathParams: [
            { name: 'namespace', description: 'Namespace name' },
            { name: 'filename', description: 'Tool filename' },
          ],
        },
        {
          method: 'POST',
          path: '/api/folders/{namespace}/files/create-from-template',
          description: 'Create tool from template',
          auth: true,
          body: '{"name":"my_tool"}',
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'PUT',
          path: '/api/folders/{namespace}/files/{filename}',
          description: 'Update tool content',
          auth: true,
          body: '{"content":"# Updated content"}',
          pathParams: [
            { name: 'namespace', description: 'Namespace name' },
            { name: 'filename', description: 'Tool filename' },
          ],
        },
        {
          method: 'POST',
          path: '/api/folders/{namespace}/files/validate',
          description: 'Validate tool without saving',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'GET',
          path: '/api/folders/{namespace}/files/deps',
          description: 'Get namespace dependencies (venv + packages)',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'POST',
          path: '/api/folders/{namespace}/files/deps/install',
          description: 'Install namespace dependencies',
          auth: true,
          body: '{"requirements":"requests==2.32.0"}',
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'POST',
          path: '/api/folders/{namespace}/files/deps/create',
          description: 'Create namespace venv',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'POST',
          path: '/api/folders/{namespace}/files/deps/uninstall',
          description: 'Uninstall namespace dependencies (pip protected)',
          auth: true,
          body: '{"packages":["requests"]}',
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'POST',
          path: '/api/folders/{namespace}/files/deps/delete',
          description: 'Delete namespace venv',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
      ],
    },
    {
      name: 'FastMCP Servers',
      description: 'Manage MCP servers (registry, repo URL, manual) and safety checks',
      endpoints: [
        {
          method: 'GET',
          path: '/api/fastmcp/registry/servers?search=github&limit=20',
          description: 'Search MCP Registry',
          auth: true,
        },
        { method: 'POST', path: '/api/fastmcp/safety/check', description: 'Run install safety assessment', auth: true },
        { method: 'GET', path: '/api/fastmcp/servers', description: 'List MCP servers', auth: true },
        {
          method: 'POST',
          path: '/api/fastmcp/servers',
          description: 'Install server from registry',
          auth: true,
          body: '{"server_id":"<registry-id>","server_name":"io.github.modelcontextprotocol/server-filesystem","namespace":"filesystem"}',
        },
        {
          method: 'POST',
          path: '/api/fastmcp/servers/repo',
          description: 'Install server from repository URL',
          auth: true,
          body: '{"repo_url":"https://github.com/org/repo.git","namespace":"repo_ns","entrypoint":"src/server.py"}',
        },
        {
          method: 'POST',
          path: '/api/fastmcp/servers/manual',
          description: 'Add manual command-based server',
          auth: true,
          body: '{"namespace":"manual","server_name":"Manual","command":"python","args":["server.py"]}',
        },
        {
          method: 'POST',
          path: '/api/fastmcp/servers/from-config',
          description: 'Add server from Claude Desktop style config',
          auth: true,
          body: '{"namespace":"cfg","config":{"command":"python","args":["-m","mcp_server_fetch"]}}',
        },
        {
          method: 'POST',
          path: '/api/fastmcp/sync',
          description: 'Re-sync running MCP servers into registry',
          auth: true,
        },
        {
          method: 'POST',
          path: '/api/fastmcp/servers/{server_id}/start',
          description: 'Start MCP server',
          auth: true,
          pathParams: [{ name: 'server_id', description: 'Server ID', default: '1' }],
        },
        {
          method: 'POST',
          path: '/api/fastmcp/servers/{server_id}/stop',
          description: 'Stop MCP server',
          auth: true,
          pathParams: [{ name: 'server_id', description: 'Server ID', default: '1' }],
        },
        {
          method: 'DELETE',
          path: '/api/fastmcp/servers/{server_id}',
          description: 'Delete MCP server',
          auth: true,
          pathParams: [{ name: 'server_id', description: 'Server ID', default: '1' }],
        },
        {
          method: 'GET',
          path: '/api/fastmcp/servers/{server_id}/config/files',
          description: 'List config files',
          auth: true,
          pathParams: [{ name: 'server_id', description: 'Server ID', default: '1' }],
        },
        {
          method: 'GET',
          path: '/api/fastmcp/servers/{server_id}/config',
          description: 'Read config content',
          auth: true,
          pathParams: [{ name: 'server_id', description: 'Server ID', default: '1' }],
        },
      ],
    },
    {
      name: 'Playground',
      description: 'Test tools through backend helper routes',
      endpoints: [
        { method: 'GET', path: '/api/playground/tools', description: 'List tools for playground', auth: true },
        {
          method: 'POST',
          path: '/api/playground/execute',
          description: 'Execute tool via OpenAPI or MCP',
          auth: true,
          body: '{"tool_name":"hello_world","arguments":{"name":"World"},"transport":"openapi","namespace":"shared"}',
        },
        {
          method: 'POST',
          path: '/api/playground/mcp',
          description: 'Send MCP-like JSON-RPC payload',
          auth: true,
          body: '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
        },
      ],
    },
    {
      name: 'Reload',
      description: 'Hot reload tools without server restart',
      endpoints: [
        { method: 'GET', path: '/api/reload/status', description: 'Get reload status and namespaces', auth: true },
        { method: 'POST', path: '/api/reload', description: 'Reload all namespaces', auth: true },
        {
          method: 'POST',
          path: '/api/reload/{namespace}',
          description: 'Reload specific namespace',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace to reload' }],
        },
      ],
    },
    {
      name: TOOL_API_CATEGORY,
      description: 'Tool API endpoints — global (/openapi) and namespace-scoped (/{namespace}/openapi)',
      endpoints: [
        { method: 'GET', path: '/health', description: 'Tool API health check', auth: false },
        { method: 'GET', path: '/tools', description: 'List all tools (global)', auth: true },
        {
          method: 'POST',
          path: '/tools/{tool_name}',
          description: 'Execute a tool (global)',
          auth: true,
          body: '{"name":"World"}',
          pathParams: [{ name: 'tool_name', description: 'Tool name', default: 'hello_world' }],
        },
        {
          method: 'GET',
          path: '/{namespace}/openapi/health',
          description: 'Namespace health check',
          auth: false,
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'GET',
          path: '/{namespace}/openapi/tools',
          description: 'List tools in namespace',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'POST',
          path: '/{namespace}/openapi/tools/{tool_name}',
          description: 'Execute tool in namespace',
          auth: true,
          body: '{"name":"World"}',
          pathParams: [
            { name: 'namespace', description: 'Namespace name' },
            { name: 'tool_name', description: 'Tool name', default: 'hello_world' },
          ],
        },
      ],
    },
    {
      name: MCP_TRANSPORT_CATEGORY,
      description: 'MCP Streamable HTTP — namespace-first (/{namespace}/mcp) and global (/mcp)',
      endpoints: [
        { method: 'GET', path: '/mcp/health', description: 'MCP health check', auth: false },
        { method: 'GET', path: '/mcp/namespaces', description: 'List MCP namespaces', auth: true },
        {
          method: 'POST',
          path: '/{namespace}/mcp',
          description: 'MCP tools/list (namespace)',
          auth: true,
          body: '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'POST',
          path: '/{namespace}/mcp',
          description: 'MCP tools/call (namespace)',
          auth: true,
          body: '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"hello_world","arguments":{"name":"World"}}}',
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'GET',
          path: '/{namespace}/mcp',
          description: 'SSE stream (namespace, requires Accept: text/event-stream)',
          auth: true,
          headers: { Accept: 'text/event-stream' },
          note: 'This keeps a streaming connection open.',
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'GET',
          path: '/{namespace}/mcp/info',
          description: 'Discovery (namespace)',
          auth: true,
          pathParams: [{ name: 'namespace', description: 'Namespace name' }],
        },
        {
          method: 'POST',
          path: '/mcp',
          description: 'Global JSON-RPC endpoint (all namespaces)',
          auth: true,
          body: '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
        },
        {
          method: 'GET',
          path: '/mcp',
          description: 'SSE stream (global, requires Accept: text/event-stream)',
          auth: true,
          headers: { Accept: 'text/event-stream' },
          note: 'This keeps a streaming connection open.',
        },
        {
          method: 'GET',
          path: '/mcp/info',
          description: 'Discovery (global)',
          auth: true,
        },
      ],
    },
  ]
}

function getMethodColor(method: string): string {
  switch (method) {
    case 'GET':
      return 'bg-green-100 text-green-700 border-green-200'
    case 'POST':
      return 'bg-blue-100 text-blue-700 border-blue-200'
    case 'PUT':
      return 'bg-yellow-100 text-yellow-700 border-yellow-200'
    case 'DELETE':
      return 'bg-red-100 text-red-700 border-red-200'
    default:
      return 'bg-gray-100 text-gray-700 border-gray-200'
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
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(['Getting Started', TOOL_API_CATEGORY, MCP_TRANSPORT_CATEGORY])
  )
  const [activeEndpoint, setActiveEndpoint] = useState<{ category: string; endpoint: Endpoint } | null>(null)
  const [pathParamValues, setPathParamValues] = useState<Record<string, string>>({})
  const [requestBody, setRequestBody] = useState('')
  const [response, setResponse] = useState<{ status: number; data: string; time: number } | null>(null)
  const [lastRequestUrl, setLastRequestUrl] = useState<string>('')
  const [isLoading, setIsLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  // Fetch all namespaces (native + fastmcp + external) for autocomplete
  const namespacesQuery = useQuery({
    queryKey: ['allNamespaces'],
    queryFn: getAllNamespaces,
    staleTime: 60000,
  })

  const activePathParams = activeEndpoint?.endpoint.pathParams || []
  const selectedNamespace = pathParamValues.namespace || ''
  const needsToolNameOptions = activePathParams.some((param) => param.name === 'tool_name')
  const needsServerIdOptions = activePathParams.some((param) => param.name === 'server_id')
  const needsFilenameOptions = activePathParams.some((param) => param.name === 'filename')

  const allToolsQuery = useQuery({
    queryKey: ['docs-all-tools'],
    queryFn: getAllTools,
    staleTime: 60000,
    enabled: needsToolNameOptions,
  })

  const fastMcpServersQuery = useQuery({
    queryKey: ['docs-fastmcp-servers'],
    queryFn: listFastMcpServers,
    staleTime: 30000,
    enabled: needsServerIdOptions,
  })

  const namespaceToolsQuery = useQuery({
    queryKey: ['docs-namespace-tools', selectedNamespace],
    queryFn: () => getTools(selectedNamespace),
    staleTime: 60000,
    enabled: needsFilenameOptions && Boolean(selectedNamespace),
  })

  const namespaces = useMemo(
    () => namespacesQuery.data?.namespaces?.map((ns) => ns.name) || [],
    [namespacesQuery.data]
  )
  const toolNameOptions: PathParamOption[] = useMemo(
    () =>
      allToolsQuery.data?.tools?.map((tool) => ({
        value: tool.name,
        label: `${tool.name} (${tool.namespace})`,
      })) || [],
    [allToolsQuery.data]
  )
  const serverIdOptions: PathParamOption[] = useMemo(
    () =>
      fastMcpServersQuery.data?.map((server) => ({
        value: String(server.id),
        label: `${server.id} - ${server.namespace} (${server.server_name})`,
      })) || [],
    [fastMcpServersQuery.data]
  )
  const filenameOptions: PathParamOption[] = useMemo(
    () =>
      namespaceToolsQuery.data?.map((tool) => ({
        value: tool.filename,
        label: tool.filename,
      })) || [],
    [namespaceToolsQuery.data]
  )
  const categories = buildCategories()
  const toolApiDocsUrl = `${window.location.origin}/openapi/docs`
  const toolApiSchemaUrl = `${window.location.origin}/openapi/openapi.json`

  const getPathParamOptions = useCallback(
    (paramName: string): PathParamOption[] => {
      if (paramName === 'namespace') {
        return namespaces.map((ns) => ({ value: ns, label: ns }))
      }
      if (paramName === 'tool_name') {
        return toolNameOptions
      }
      if (paramName === 'server_id') {
        return serverIdOptions
      }
      if (paramName === 'filename') {
        return filenameOptions
      }
      return []
    },
    [namespaces, toolNameOptions, serverIdOptions, filenameOptions]
  )

  // Load token from localStorage on mount
  useEffect(() => {
    const savedToken = localStorage.getItem('tooldock_token') || ''
    setToken(savedToken)
  }, [])

  // Save token to localStorage when changed
  const handleTokenChange = (newToken: string) => {
    setToken(newToken)
    if (newToken) {
      localStorage.setItem('tooldock_token', newToken)
    } else {
      localStorage.removeItem('tooldock_token')
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

    // Initialize path params with defaults or first available namespace
    const initialParams: Record<string, string> = {}
    if (endpoint.pathParams) {
      for (const param of endpoint.pathParams) {
        if (param.default) {
          initialParams[param.name] = param.default
        } else if (param.name === 'namespace' && namespaces.length > 0) {
          initialParams[param.name] = namespaces[0]
        } else {
          initialParams[param.name] = ''
        }
      }
    }
    setPathParamValues(initialParams)
  }

  useEffect(() => {
    if (!activeEndpoint?.endpoint.pathParams) return
    let changed = false
    const nextValues: Record<string, string> = { ...pathParamValues }
    for (const param of activeEndpoint.endpoint.pathParams) {
      if (nextValues[param.name]) continue
      const options = getPathParamOptions(param.name)
      if (options.length > 0) {
        nextValues[param.name] = options[0].value
        changed = true
      }
    }
    if (changed) {
      setPathParamValues(nextValues)
    }
  }, [activeEndpoint, pathParamValues, getPathParamOptions])

  const getResolvedPath = (): string => {
    if (!activeEndpoint) return ''
    let path = activeEndpoint.endpoint.path
    for (const [key, value] of Object.entries(pathParamValues)) {
      path = path.replace(`{${key}}`, value || `{${key}}`)
    }
    return path
  }

  const getBaseUrlForCategory = (categoryName: string): string => {
    if (categoryName === TOOL_API_CATEGORY) {
      // Namespace-scoped routes (/{ns}/openapi/*) go to gateway root;
      // global routes (/health, /tools/*) go via /openapi prefix.
      const resolvedPath = getResolvedPath()
      if (resolvedPath.match(/^\/[^/]+\/openapi/)) {
        return window.location.origin
      }
      return `${window.location.origin}/openapi`
    }
    if (categoryName === MCP_TRANSPORT_CATEGORY) {
      return window.location.origin
    }
    return window.location.origin
  }

  const executeRequest = async () => {
    if (!activeEndpoint) return

    setIsLoading(true)
    setResponse(null)
    setLastRequestUrl('')

    const startTime = Date.now()
    const endpoint = activeEndpoint.endpoint

    try {
    const baseUrl = getBaseUrlForCategory(activeEndpoint.category)
    const url = `${baseUrl}${getResolvedPath()}`
    setLastRequestUrl(url)

      const headers: Record<string, string> = {}
      if (endpoint.headers) {
        for (const [key, value] of Object.entries(endpoint.headers)) {
          headers[key] = value
        }
      }
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
        time: duration,
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
    const baseUrl = getBaseUrlForCategory(activeEndpoint.category)
    const url = `${baseUrl}${getResolvedPath()}`

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
      </div>

      {/* Quick Links */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 mb-4">
        <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">Quick Links</div>
        <div className="flex flex-wrap gap-2">
          <a
            href={toolApiDocsUrl || '#'}
            target="_blank"
            rel="noopener noreferrer"
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
              toolApiDocsUrl ? 'bg-gray-100 hover:bg-gray-200' : 'bg-gray-50 text-gray-400 cursor-not-allowed'
            }`}
          >
            Tool API Swagger
            <ExternalLink className="w-3 h-3" />
          </a>
          <a
            href={toolApiSchemaUrl || '#'}
            target="_blank"
            rel="noopener noreferrer"
            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors ${
              toolApiSchemaUrl
                ? 'bg-gray-100 hover:bg-gray-200'
                : 'bg-gray-50 text-gray-400 cursor-not-allowed'
            }`}
          >
            Tool API Schema
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>
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

      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 mb-4">
        <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">Base URL</div>
        <p className="text-sm text-gray-700">
          This UI routes through the gateway at <span className="font-mono">{window.location.origin}</span> using
          <span className="font-mono"> /api</span>, <span className="font-mono">/openapi</span>, and{' '}
          <span className="font-mono">/mcp</span>.
          Namespace-scoped routes use <span className="font-mono">/{'{namespace}'}/mcp</span> and{' '}
          <span className="font-mono">/{'{namespace}'}/openapi</span>.
        </p>
      </div>

      <div className="flex-1 flex gap-4 min-h-0">
        {/* Endpoints List */}
        <div className="w-96 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
          <div className="p-3 border-b border-gray-200 bg-gray-50">
            <h2 className="font-semibold text-gray-700">Endpoints</h2>
          </div>
          <div className="flex-1 overflow-auto">
            {categories.map((category) => (
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
                          activeEndpoint?.endpoint === endpoint
                            ? 'bg-primary-50 border-l-2 border-primary-500'
                            : ''
                        }`}
                      >
                        <span
                          className={`px-1.5 py-0.5 text-xs font-bold rounded border ${getMethodColor(
                            endpoint.method
                          )}`}
                        >
                          {endpoint.method}
                        </span>
                        <div className="flex-1 min-w-0">
                          <span
                            className="text-sm text-gray-600 truncate block"
                            title={endpoint.path}
                          >
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
                    <span
                      className={`px-2 py-1 text-sm font-bold rounded border ${getMethodColor(
                        activeEndpoint.endpoint.method
                      )}`}
                    >
                      {activeEndpoint.endpoint.method}
                    </span>
                    <code className="text-sm text-gray-700">{getResolvedPath()}</code>
                  </div>
                  {lastRequestUrl && (
                    <div className="text-xs text-gray-500">
                      Request URL: <span className="font-mono">{lastRequestUrl}</span>
                    </div>
                  )}
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
                  {activeEndpoint.endpoint.note && (
                    <p className="text-xs text-gray-500 mb-2">{activeEndpoint.endpoint.note}</p>
                  )}
                  {activeEndpoint.endpoint.auth && !token && (
                    <p className="text-sm text-yellow-600 mb-2">
                      This endpoint requires authentication. Enter a token above.
                    </p>
                  )}

                  {/* Path Parameters */}
                  {activeEndpoint.endpoint.pathParams &&
                    activeEndpoint.endpoint.pathParams.length > 0 && (
                      <div className="mt-3 space-y-2">
                        <label className="block text-sm font-medium text-gray-700">
                          Path Parameters:
                        </label>
                        <div className="grid grid-cols-2 gap-2">
                          {activeEndpoint.endpoint.pathParams.map((param) => (
                            <div key={param.name}>
                              <label className="block text-xs text-gray-500 mb-1">
                                {param.name}
                                {param.description && (
                                  <span className="text-gray-400"> - {param.description}</span>
                                )}
                              </label>
                              {getPathParamOptions(param.name).length > 0 ? (
                                <select
                                  value={pathParamValues[param.name] || ''}
                                  onChange={(e) =>
                                    setPathParamValues((prev) => ({
                                      ...prev,
                                      [param.name]: e.target.value,
                                    }))
                                  }
                                  className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                                >
                                  {getPathParamOptions(param.name).map((option) => (
                                    <option key={option.value} value={option.value}>
                                      {option.label}
                                    </option>
                                  ))}
                                </select>
                              ) : (
                                <input
                                  type="text"
                                  value={pathParamValues[param.name] || ''}
                                  onChange={(e) =>
                                    setPathParamValues((prev) => ({
                                      ...prev,
                                      [param.name]: e.target.value,
                                    }))
                                  }
                                  placeholder={param.default || param.name}
                                  className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none font-mono"
                                />
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                  {activeEndpoint.endpoint.body && (
                    <div className="mt-3">
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        Request Body:
                      </label>
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
                      {copied ? (
                        <Check className="w-4 h-4 text-green-600" />
                      ) : (
                        <Copy className="w-4 h-4" />
                      )}
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

import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import CodeMirror from '@uiw/react-codemirror'
import { json } from '@codemirror/lang-json'
import { getAllTools, executePlaygroundTool, syncFastMcpServers, PlaygroundTool } from '../api/client'
import { Play, Check, X, Loader2, RefreshCw, FolderTree, Wrench, Server, Globe } from 'lucide-react'

type Transport = 'openapi' | 'mcp'
type ToolScope = 'internal' | 'external'

export default function Playground() {
  const [selectedNamespace, setSelectedNamespace] = useState<string | null>(null)
  const [selectedTool, setSelectedTool] = useState<string | null>(null)
  const [inputJson, setInputJson] = useState('{}')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const [transport, setTransport] = useState<Transport>('openapi')
  const [scope, setScope] = useState<ToolScope>('internal')
  const queryClient = useQueryClient()

  const toolsQuery = useQuery({
    queryKey: ['playgroundTools'],
    queryFn: getAllTools,
    refetchOnWindowFocus: true,
    staleTime: 30000,
  })

  const executeMutation = useMutation({
    mutationFn: ({ name, payload, transport, namespace }: { name: string; payload: Record<string, unknown>; transport: Transport; namespace?: string }) =>
      executePlaygroundTool(name, payload, transport, namespace),
  })

  const tools = toolsQuery.data?.tools || []
  const scopedTools = useMemo(() => {
    if (scope === 'external') {
      return tools.filter((tool) => tool.type === 'external')
    }
    return tools.filter((tool) => tool.type !== 'external')
  }, [tools, scope])

  // Group tools by namespace
  const namespaces = useMemo(() => {
    const grouped: Record<string, PlaygroundTool[]> = {}
    for (const tool of scopedTools) {
      const ns = tool.namespace || 'shared'
      if (!grouped[ns]) {
        grouped[ns] = []
      }
      grouped[ns].push(tool)
    }
    return Object.entries(grouped)
      .map(([name, tools]) => ({ name, tools, count: tools.length }))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [scopedTools])

  // Tools in selected namespace
  const namespacedTools = useMemo(() => {
    if (!selectedNamespace) return []
    return namespaces.find((ns) => ns.name === selectedNamespace)?.tools || []
  }, [namespaces, selectedNamespace])

  const selectedToolInfo = scopedTools.find((t) => t.name === selectedTool)

  const handleNamespaceSelect = (name: string) => {
    setSelectedNamespace(name)
    setSelectedTool(null)
    executeMutation.reset()
  }

  const handleScopeSelect = async (nextScope: ToolScope) => {
    setScope(nextScope)
    setSelectedNamespace(null)
    setSelectedTool(null)
    executeMutation.reset()
    if (nextScope === 'external') {
      setSyncing(true)
      try {
        await syncFastMcpServers()
      } catch {
        // best-effort
      } finally {
        setSyncing(false)
      }
      queryClient.invalidateQueries({ queryKey: ['playgroundTools'] })
    }
  }

  const handleToolSelect = (name: string) => {
    setSelectedTool(name)
    setInputJson('{}')
    setJsonError(null)
    executeMutation.reset()

    // Generate example input from schema
    const tool = scopedTools.find((t) => t.name === name)
    if (tool?.input_schema?.properties) {
      const example: Record<string, unknown> = {}
      for (const [key, prop] of Object.entries(
        tool.input_schema.properties as Record<string, { type?: string; default?: unknown }>
      )) {
        if (prop.default !== undefined) {
          example[key] = prop.default
        } else if (prop.type === 'string') {
          example[key] = ''
        } else if (prop.type === 'number' || prop.type === 'integer') {
          example[key] = 0
        } else if (prop.type === 'boolean') {
          example[key] = false
        }
      }
      setInputJson(JSON.stringify(example, null, 2))
    }
  }

  const handleInputChange = (value: string) => {
    setInputJson(value)
    try {
      JSON.parse(value)
      setJsonError(null)
    } catch (e) {
      setJsonError((e as Error).message)
    }
  }

  const handleExecute = () => {
    if (!selectedTool || jsonError) return

    try {
      const payload = JSON.parse(inputJson)
      executeMutation.mutate({ name: selectedTool, payload, transport, namespace: selectedNamespace || undefined })
    } catch (e) {
      setJsonError((e as Error).message)
    }
  }

  const [syncing, setSyncing] = useState(false)

  const handleRefresh = async () => {
    if (scope === 'external') {
      setSyncing(true)
      try {
        await syncFastMcpServers()
      } catch {
        // sync is best-effort; tools will still be fetched
      } finally {
        setSyncing(false)
      }
    }
    queryClient.invalidateQueries({ queryKey: ['playgroundTools'] })
  }

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Playground</h1>
        <div className="flex items-center gap-4">
          {/* Transport selector */}
          <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
            <button
              onClick={() => setTransport('openapi')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-colors ${
                transport === 'openapi'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Globe className="w-4 h-4" />
              OpenAPI
            </button>
            <button
              onClick={() => setTransport('mcp')}
              className={`flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md transition-colors ${
                transport === 'mcp'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              <Server className="w-4 h-4" />
              MCP
            </button>
          </div>

          <button
            onClick={handleRefresh}
            disabled={toolsQuery.isRefetching || syncing}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${toolsQuery.isRefetching || syncing ? 'animate-spin' : ''}`} />
            {syncing ? 'Syncing...' : 'Refresh Tools'}
          </button>
        </div>
      </div>

      <div className="flex-1 flex gap-4 min-h-0">
        {/* Namespace List */}
        <div className="w-48 bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col">
          <div className="p-3 border-b border-gray-200 font-medium text-gray-900 flex items-center gap-2">
            <FolderTree className="w-4 h-4" />
            Namespaces
          </div>

          <div className="p-2 border-b border-gray-200">
            <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
              <button
                onClick={() => handleScopeSelect('internal')}
                className={`flex-1 px-2 py-1 text-xs rounded-md transition-colors ${
                  scope === 'internal'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                Internal
              </button>
              <button
                onClick={() => handleScopeSelect('external')}
                className={`flex-1 px-2 py-1 text-xs rounded-md transition-colors ${
                  scope === 'external'
                    ? 'bg-white text-gray-900 shadow-sm'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                External
              </button>
            </div>
          </div>

          <div className="flex-1 overflow-auto">
            {toolsQuery.isLoading ? (
              <div className="p-3 text-gray-500 text-sm">Loading...</div>
            ) : namespaces.length === 0 ? (
              <div className="p-3 text-gray-500 text-sm">
                {scope === 'external' ? 'No external namespaces' : 'No internal namespaces'}
              </div>
            ) : (
              <ul className="divide-y divide-gray-100">
                {namespaces.map((ns) => (
                  <li key={ns.name}>
                    <button
                      onClick={() => handleNamespaceSelect(ns.name)}
                      className={`w-full p-3 text-left transition-colors ${
                        selectedNamespace === ns.name
                          ? 'bg-primary-50 border-l-2 border-primary-600'
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-gray-900 text-sm">{ns.name}</span>
                        <span className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded">
                          {ns.count}
                        </span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Tool List */}
        <div className="w-64 bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col">
          <div className="p-3 border-b border-gray-200 font-medium text-gray-900 flex items-center gap-2">
            <Wrench className="w-4 h-4" />
            Tools
            {selectedNamespace && (
              <span className="text-xs text-gray-500 font-normal">in {selectedNamespace}</span>
            )}
          </div>

          <div className="flex-1 overflow-auto">
            {!selectedNamespace ? (
              <div className="p-3 text-gray-500 text-sm">Select a namespace</div>
            ) : namespacedTools.length === 0 ? (
              <div className="p-3 text-gray-500 text-sm">No tools in this namespace</div>
            ) : (
              <ul className="divide-y divide-gray-100">
                {namespacedTools.map((tool) => (
                  <li key={tool.name}>
                    <button
                      onClick={() => handleToolSelect(tool.name)}
                      className={`w-full p-3 text-left transition-colors ${
                        selectedTool === tool.name
                          ? 'bg-primary-50 border-l-2 border-primary-600'
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      <div className="font-medium text-gray-900 text-sm">{tool.name}</div>
                      <div className="text-xs text-gray-500 mt-1 line-clamp-2">
                        {tool.description}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Main Area */}
        <div className="flex-1 flex flex-col gap-4 min-h-0">
          {selectedTool ? (
            <>
              {/* Tool Info */}
              <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
                <div className="flex items-center gap-2">
                  <h2 className="font-semibold text-gray-900">{selectedTool}</h2>
                  <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                    {selectedToolInfo?.type}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded ${
                      transport === 'mcp'
                        ? 'bg-purple-100 text-purple-700'
                        : 'bg-blue-100 text-blue-700'
                    }`}
                  >
                    via {transport === 'mcp' ? 'MCP' : 'OpenAPI'}
                  </span>
                </div>
                <p className="text-sm text-gray-600 mt-1">{selectedToolInfo?.description}</p>
              </div>

              {/* Input/Output */}
              <div className="flex-1 grid grid-cols-2 gap-4 min-h-0">
                {/* Input */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col">
                  <div className="flex items-center justify-between p-3 border-b border-gray-200">
                    <span className="font-medium text-gray-900">Input (JSON)</span>
                    <button
                      onClick={handleExecute}
                      disabled={!!jsonError || executeMutation.isPending}
                      className="flex items-center gap-2 px-3 py-1.5 text-sm bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white rounded transition-colors"
                    >
                      {executeMutation.isPending ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Play className="w-4 h-4" />
                      )}
                      Execute
                    </button>
                  </div>

                  {jsonError && (
                    <div className="px-3 py-2 bg-red-50 border-b border-red-200 text-sm text-red-600">
                      {jsonError}
                    </div>
                  )}

                  <div className="flex-1 overflow-auto">
                    <CodeMirror
                      value={inputJson}
                      onChange={handleInputChange}
                      extensions={[json()]}
                      theme="light"
                      className="h-full"
                      basicSetup={{
                        lineNumbers: true,
                        foldGutter: true,
                      }}
                    />
                  </div>
                </div>

                {/* Output */}
                <div className="bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col">
                  <div className="flex items-center gap-2 p-3 border-b border-gray-200">
                    <span className="font-medium text-gray-900">Output</span>
                    {executeMutation.isSuccess && executeMutation.data?.success && (
                      <Check className="w-4 h-4 text-green-600" />
                    )}
                    {(executeMutation.isError || (executeMutation.data && !executeMutation.data.success)) && (
                      <X className="w-4 h-4 text-red-600" />
                    )}
                    {executeMutation.data && (
                      <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                        {executeMutation.data.transport}
                      </span>
                    )}
                    {executeMutation.data?.error_type && (
                      <span
                        className={`text-xs px-2 py-0.5 rounded ${
                          executeMutation.data.error_type === 'network'
                            ? 'bg-yellow-100 text-yellow-700'
                            : 'bg-red-100 text-red-700'
                        }`}
                      >
                        {executeMutation.data.error_type === 'network' ? 'Network' : 'Tool Server'}
                      </span>
                    )}
                    {executeMutation.isError && (
                      <span className="text-xs px-2 py-0.5 rounded bg-yellow-100 text-yellow-700">
                        Network (Admin API)
                      </span>
                    )}
                  </div>

                  <div className="flex-1 overflow-auto p-3">
                    {executeMutation.isPending ? (
                      <div className="flex items-center gap-2 text-gray-500">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Executing via {transport}...
                      </div>
                    ) : executeMutation.isError ? (
                      <div className="text-red-600">
                        <div className="font-medium">Error</div>
                        <pre className="mt-2 text-sm whitespace-pre-wrap">
                          {executeMutation.error.message}
                        </pre>
                      </div>
                    ) : executeMutation.data ? (
                      executeMutation.data.success ? (
                        <pre className="text-sm whitespace-pre-wrap font-mono">
                          {JSON.stringify(executeMutation.data.result, null, 2)}
                        </pre>
                      ) : (
                        <div className="text-red-600">
                          <div className="font-medium">Execution Failed</div>
                          <pre className="mt-2 text-sm whitespace-pre-wrap">
                            {executeMutation.data.error}
                          </pre>
                        </div>
                      )
                    ) : (
                      <div className="text-gray-400 text-sm">Click "Execute" to run the tool</div>
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center bg-white rounded-xl shadow-sm border border-gray-200 text-gray-500">
              {selectedNamespace
                ? 'Select a tool from the list to test it'
                : 'Select a namespace, then a tool to test it'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

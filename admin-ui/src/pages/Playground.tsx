import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import CodeMirror from '@uiw/react-codemirror'
import { json } from '@codemirror/lang-json'
import { getAllTools, executeTool } from '../api/client'
import { Play, Check, X, Loader2, RefreshCw } from 'lucide-react'

export default function Playground() {
  const [selectedTool, setSelectedTool] = useState<string | null>(null)
  const [inputJson, setInputJson] = useState('{}')
  const [jsonError, setJsonError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const toolsQuery = useQuery({
    queryKey: ['allTools'],
    queryFn: getAllTools,
    refetchOnWindowFocus: true,
    staleTime: 30000, // Consider stale after 30 seconds
  })

  const executeMutation = useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: Record<string, unknown> }) =>
      executeTool(name, payload),
  })

  const tools = toolsQuery.data?.tools || []
  const selectedToolInfo = tools.find((t) => t.name === selectedTool)

  const handleToolSelect = (name: string) => {
    setSelectedTool(name)
    setInputJson('{}')
    setJsonError(null)
    executeMutation.reset()

    // Generate example input from schema
    const tool = tools.find((t) => t.name === name)
    if (tool?.input_schema?.properties) {
      const example: Record<string, unknown> = {}
      for (const [key, prop] of Object.entries(tool.input_schema.properties as Record<string, { type?: string; default?: unknown }>)) {
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
      executeMutation.mutate({ name: selectedTool, payload })
    } catch (e) {
      setJsonError((e as Error).message)
    }
  }

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['allTools'] })
  }

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Playground</h1>
        <button
          onClick={handleRefresh}
          disabled={toolsQuery.isRefetching}
          className="flex items-center gap-2 px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${toolsQuery.isRefetching ? 'animate-spin' : ''}`} />
          Refresh Tools
        </button>
      </div>

      <div className="flex-1 flex gap-4 min-h-0">
        {/* Tool List */}
        <div className="w-72 bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col">
          <div className="p-3 border-b border-gray-200 font-medium text-gray-900">
            Available Tools
          </div>

          <div className="flex-1 overflow-auto">
            {toolsQuery.isLoading ? (
              <div className="p-3 text-gray-500 text-sm">Loading...</div>
            ) : tools.length === 0 ? (
              <div className="p-3 text-gray-500 text-sm">No tools available</div>
            ) : (
              <ul className="divide-y divide-gray-100">
                {tools.map((tool) => (
                  <li key={tool.name}>
                    <button
                      onClick={() => handleToolSelect(tool.name)}
                      className={`w-full p-3 text-left transition-colors ${
                        selectedTool === tool.name
                          ? 'bg-primary-50 border-l-2 border-primary-600'
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      <div className="font-medium text-gray-900 text-sm">
                        {tool.name}
                      </div>
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
                <h2 className="font-semibold text-gray-900">{selectedTool}</h2>
                <p className="text-sm text-gray-600 mt-1">
                  {selectedToolInfo?.description}
                </p>
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
                    {executeMutation.isSuccess && (
                      <Check className="w-4 h-4 text-green-600" />
                    )}
                    {executeMutation.isError && (
                      <X className="w-4 h-4 text-red-600" />
                    )}
                  </div>

                  <div className="flex-1 overflow-auto p-3">
                    {executeMutation.isPending ? (
                      <div className="flex items-center gap-2 text-gray-500">
                        <Loader2 className="w-4 h-4 animate-spin" />
                        Executing...
                      </div>
                    ) : executeMutation.isError ? (
                      <div className="text-red-600">
                        <div className="font-medium">Error</div>
                        <pre className="mt-2 text-sm whitespace-pre-wrap">
                          {executeMutation.error.message}
                        </pre>
                      </div>
                    ) : executeMutation.data ? (
                      <pre className="text-sm whitespace-pre-wrap font-mono">
                        {JSON.stringify(executeMutation.data.result, null, 2)}
                      </pre>
                    ) : (
                      <div className="text-gray-400 text-sm">
                        Click "Execute" to run the tool
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center bg-white rounded-xl shadow-sm border border-gray-200 text-gray-500">
              Select a tool from the list to test it
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

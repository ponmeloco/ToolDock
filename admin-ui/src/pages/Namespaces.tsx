import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getNamespaces, createNamespace, deleteNamespace, getAllNamespaces } from '../api/client'
import {
  Folder,
  Plus,
  Trash2,
  ChevronRight,
  AlertTriangle,
  Server,
  Cloud,
  RefreshCw,
} from 'lucide-react'

type ViewMode = 'native' | 'all'

export default function Namespaces() {
  const [newName, setNewName] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<ViewMode>('all')
  const queryClient = useQueryClient()

  // Native namespaces (file-based)
  const nativeNamespacesQuery = useQuery({
    queryKey: ['namespaces'],
    queryFn: getNamespaces,
  })

  // All namespaces (native + fastmcp + external)
  const allNamespacesQuery = useQuery({
    queryKey: ['allNamespaces'],
    queryFn: getAllNamespaces,
    enabled: viewMode === 'all',
  })

  const createMutation = useMutation({
    mutationFn: createNamespace,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['namespaces'] })
      queryClient.invalidateQueries({ queryKey: ['allNamespaces'] })
      setNewName('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteNamespace,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['namespaces'] })
      queryClient.invalidateQueries({ queryKey: ['allNamespaces'] })
      setDeleteConfirm(null)
    },
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (newName.trim()) {
      createMutation.mutate(newName.trim().toLowerCase())
    }
  }

  const handleRefresh = () => {
    queryClient.invalidateQueries({ queryKey: ['namespaces'] })
    queryClient.invalidateQueries({ queryKey: ['allNamespaces'] })
  }

  const getTypeIcon = (type: string) => {
    switch (type) {
      case 'fastmcp':
        return <Server className="w-5 h-5 text-purple-600" />
      case 'external':
        return <Cloud className="w-5 h-5 text-blue-600" />
      default:
        return <Folder className="w-5 h-5 text-primary-600" />
    }
  }

  const getTypeLabel = (type: string) => {
    switch (type) {
      case 'fastmcp':
        return (
          <span className="text-xs px-1.5 py-0.5 rounded bg-purple-100 text-purple-700">
            FastMCP
          </span>
        )
      case 'external':
        return (
          <span className="text-xs px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">
            External
          </span>
        )
      default:
        return (
          <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700">
            Native
          </span>
        )
    }
  }

  const getStatusBadge = (status: string | null) => {
    if (!status) return null
    switch (status) {
      case 'running':
        return (
          <span className="text-xs px-1.5 py-0.5 rounded bg-green-100 text-green-700">
            Running
          </span>
        )
      case 'stopped':
        return (
          <span className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
            Stopped
          </span>
        )
      case 'error':
        return (
          <span className="text-xs px-1.5 py-0.5 rounded bg-red-100 text-red-700">
            Error
          </span>
        )
      default:
        return null
    }
  }

  // Combine data based on view mode
  const displayNamespaces = viewMode === 'all'
    ? allNamespacesQuery.data?.namespaces || []
    : (nativeNamespacesQuery.data || []).map(ns => ({
        name: ns.name,
        type: 'native' as const,
        tool_count: ns.tool_count,
        status: 'active',
        endpoint: `/mcp/${ns.name}`,
      }))

  const isLoading = viewMode === 'all' ? allNamespacesQuery.isLoading : nativeNamespacesQuery.isLoading
  const error = viewMode === 'all' ? allNamespacesQuery.error : nativeNamespacesQuery.error

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Namespaces</h1>
        <div className="flex items-center gap-2">
          {/* View Mode Toggle */}
          <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
            <button
              onClick={() => setViewMode('all')}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                viewMode === 'all'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              All Types
            </button>
            <button
              onClick={() => setViewMode('native')}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                viewMode === 'native'
                  ? 'bg-white text-gray-900 shadow-sm'
                  : 'text-gray-600 hover:text-gray-900'
              }`}
            >
              Native Only
            </button>
          </div>
          <button
            onClick={handleRefresh}
            className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Create Namespace */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Create Native Namespace</h2>
        <form onSubmit={handleCreate} className="flex gap-3">
          <input
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            placeholder="namespace-name"
            pattern="[a-z][a-z0-9_-]*"
            title="Lowercase letters, numbers, underscores, hyphens. Must start with a letter."
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          />
          <button
            type="submit"
            disabled={createMutation.isPending || !newName.trim()}
            className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            Create
          </button>
        </form>
        {createMutation.error && (
          <p className="mt-2 text-sm text-red-600">
            {createMutation.error.message}
          </p>
        )}
      </div>

      {/* Namespace List */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="p-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-gray-900">
            {viewMode === 'all' ? 'All Namespaces' : 'Native Namespaces'}
          </h2>
          {allNamespacesQuery.data && viewMode === 'all' && (
            <span className="text-sm text-gray-500">
              {allNamespacesQuery.data.total} total
            </span>
          )}
        </div>

        {isLoading ? (
          <div className="p-6 text-gray-500">Loading...</div>
        ) : error ? (
          <div className="p-6 text-red-500">Failed to load namespaces</div>
        ) : displayNamespaces.length === 0 ? (
          <div className="p-6 text-gray-500 text-center">
            No namespaces yet. Create one above or add a FastMCP server.
          </div>
        ) : (
          <ul className="divide-y divide-gray-200">
            {displayNamespaces.map((ns) => {
              const isNative = ns.type === 'native'
              const linkTo = isNative
                ? `/namespaces/${ns.name}`
                : ns.type === 'fastmcp'
                ? `/fastmcp`
                : '#'

              return (
                <li key={`${ns.type}-${ns.name}`} className="p-4 hover:bg-gray-50">
                  <div className="flex items-center justify-between">
                    <Link
                      to={linkTo}
                      className="flex items-center gap-3 flex-1"
                    >
                      {getTypeIcon(ns.type)}
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900">{ns.name}</span>
                          {getTypeLabel(ns.type)}
                          {ns.type !== 'native' && getStatusBadge(ns.status)}
                        </div>
                        <div className="flex items-center gap-3 text-sm text-gray-500">
                          {ns.type === 'native' && (
                            <span>
                              {ns.tool_count} tool{ns.tool_count !== 1 ? 's' : ''}
                            </span>
                          )}
                          {ns.endpoint && (
                            <code className="text-xs bg-gray-100 px-1.5 py-0.5 rounded">
                              {ns.endpoint}
                            </code>
                          )}
                        </div>
                      </div>
                      <ChevronRight className="w-5 h-5 text-gray-400 ml-auto" />
                    </Link>

                    {/* Delete button only for native namespaces */}
                    {isNative && (
                      <>
                        {deleteConfirm === ns.name ? (
                          <div className="flex items-center gap-2 ml-4">
                            <span className="text-sm text-gray-600">Delete?</span>
                            <button
                              onClick={() => deleteMutation.mutate(ns.name)}
                              disabled={deleteMutation.isPending}
                              className="px-2 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
                            >
                              Yes
                            </button>
                            <button
                              onClick={() => setDeleteConfirm(null)}
                              className="px-2 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300"
                            >
                              No
                            </button>
                          </div>
                        ) : (
                          <button
                            onClick={() => setDeleteConfirm(ns.name)}
                            className="p-2 text-gray-400 hover:text-red-600 transition-colors ml-4"
                            title="Delete namespace"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {/* Legend */}
      {viewMode === 'all' && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <div className="text-sm font-medium text-gray-700 mb-2">Namespace Types</div>
          <div className="flex flex-wrap gap-4 text-sm text-gray-600">
            <div className="flex items-center gap-2">
              <Folder className="w-4 h-4 text-primary-600" />
              <span>Native - Python tools in tooldock_data/tools/</span>
            </div>
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-purple-600" />
              <span>FastMCP - MCP servers from registry, repo URL, or manual config</span>
            </div>
            <div className="flex items-center gap-2">
              <Cloud className="w-4 h-4 text-blue-600" />
              <span>External - Reserved for non-native integrations</span>
            </div>
          </div>
        </div>
      )}

      {/* Warning */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex gap-3">
        <AlertTriangle className="w-5 h-5 text-yellow-600 flex-shrink-0" />
        <div className="text-sm text-yellow-800">
          <strong>Note:</strong> Deleting a native namespace will remove all tools within it.
          FastMCP servers can be managed from the MCP Servers page.
        </div>
      </div>
    </div>
  )
}

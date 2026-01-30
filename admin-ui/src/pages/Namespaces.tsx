import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getNamespaces, createNamespace, deleteNamespace } from '../api/client'
import {
  Folder,
  Plus,
  Trash2,
  ChevronRight,
  AlertTriangle,
} from 'lucide-react'

export default function Namespaces() {
  const [newName, setNewName] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const namespacesQuery = useQuery({
    queryKey: ['namespaces'],
    queryFn: getNamespaces,
  })

  const createMutation = useMutation({
    mutationFn: createNamespace,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['namespaces'] })
      setNewName('')
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteNamespace,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['namespaces'] })
      setDeleteConfirm(null)
    },
  })

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault()
    if (newName.trim()) {
      createMutation.mutate(newName.trim().toLowerCase())
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Namespaces</h1>
      </div>

      {/* Create Namespace */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Create Namespace</h2>
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
        <div className="p-4 border-b border-gray-200">
          <h2 className="text-lg font-semibold text-gray-900">All Namespaces</h2>
        </div>

        {namespacesQuery.isLoading ? (
          <div className="p-6 text-gray-500">Loading...</div>
        ) : namespacesQuery.error ? (
          <div className="p-6 text-red-500">Failed to load namespaces</div>
        ) : namespacesQuery.data?.length === 0 ? (
          <div className="p-6 text-gray-500 text-center">
            No namespaces yet. Create one above.
          </div>
        ) : (
          <ul className="divide-y divide-gray-200">
            {namespacesQuery.data?.map((ns) => (
              <li key={ns.name} className="p-4 hover:bg-gray-50">
                <div className="flex items-center justify-between">
                  <Link
                    to={`/namespaces/${ns.name}`}
                    className="flex items-center gap-3 flex-1"
                  >
                    <Folder className="w-5 h-5 text-primary-600" />
                    <div>
                      <div className="font-medium text-gray-900">{ns.name}</div>
                      <div className="text-sm text-gray-500">
                        {ns.tool_count} tool{ns.tool_count !== 1 ? 's' : ''}
                      </div>
                    </div>
                    <ChevronRight className="w-5 h-5 text-gray-400 ml-auto" />
                  </Link>

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
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Warning */}
      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex gap-3">
        <AlertTriangle className="w-5 h-5 text-yellow-600 flex-shrink-0" />
        <div className="text-sm text-yellow-800">
          <strong>Note:</strong> Deleting a namespace will remove all tools within it.
          This action cannot be undone.
        </div>
      </div>
    </div>
  )
}

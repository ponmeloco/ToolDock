import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addFastMcpServer,
  checkRegistryHealth,
  deleteFastMcpServer,
  listFastMcpServers,
  searchRegistryServers,
  startFastMcpServer,
  stopFastMcpServer,
} from '../api/client'

export default function FastMCPServers() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [namespace, setNamespace] = useState('')
  const [version, setVersion] = useState('')
  const [selectedServer, setSelectedServer] = useState<{ id: string; name: string } | null>(null)

  const suggestNamespace = (serverName: string): string => {
    const raw = serverName.split('/').pop() || serverName
    let slug = raw.toLowerCase().replace(/[^a-z0-9_-]+/g, '-')
    slug = slug.replace(/^-+|-+$/g, '')
    if (!slug) slug = 'namespace'
    if (!/^[a-z]/.test(slug)) slug = `ns-${slug}`
    return slug
  }

  const getRegistryName = (server: any): string => {
    return (
      server?.name ||
      server?.server?.name ||
      server?.id ||
      ''
    )
  }

  const getRegistryId = (server: any): string => {
    return (
      server?.id ||
      server?.server?.id ||
      ''
    )
  }

  const getRegistryDescription = (server: any): string => {
    return (
      server?.description ||
      server?.server?.description ||
      server?.summary ||
      server?.server?.summary ||
      'No description'
    )
  }

  const serversQuery = useQuery({
    queryKey: ['fastmcpServers'],
    queryFn: listFastMcpServers,
  })

  const registryHealthQuery = useQuery({
    queryKey: ['fastmcpRegistryHealth'],
    queryFn: checkRegistryHealth,
    staleTime: 60000,
    refetchInterval: 60000,
  })

  const registryOnline = registryHealthQuery.data?.status === 'ok'
  const registryHealthError = registryHealthQuery.error as Error | null

  const registryQuery = useQuery({
    queryKey: ['fastmcpRegistry', search],
    queryFn: () => searchRegistryServers(search, 20),
    enabled: search.trim().length >= 2 && registryOnline,
  })

  const addMutation = useMutation({
    mutationFn: () => {
      if (!selectedServer || !namespace) {
        throw new Error('Select a server and enter a namespace')
      }
      if (!selectedServer.id) {
        throw new Error('Selected server is missing a registry id')
      }
      return addFastMcpServer(selectedServer.id, selectedServer.name, namespace, version || undefined)
    },
    onSuccess: () => {
      setNamespace('')
      setVersion('')
      setSelectedServer(null)
      queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] })
    },
  })

  const startMutation = useMutation({
    mutationFn: (id: number) => startFastMcpServer(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] }),
  })

  const stopMutation = useMutation({
    mutationFn: (id: number) => stopFastMcpServer(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] }),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteFastMcpServer(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] }),
  })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">External FastMCP Servers</h1>
        <p className="text-gray-600 text-sm">Install from the MCP Registry and expose via namespaces.</p>
      </div>

      <div className={`bg-white rounded-xl shadow-sm border border-gray-200 p-4 space-y-3 ${registryOnline ? '' : 'opacity-60'}`}>
        <div className="text-xs text-gray-400 uppercase tracking-wide">Registry Search</div>
        <div className="text-xs text-gray-500">
          Showing installable servers only (PyPI or repo-based).
        </div>
        {!registryOnline ? (
          <div className="text-sm text-gray-600">
            {registryHealthError?.message?.toLowerCase().includes('unauthorized')
              ? 'Enter a valid token to check registry connectivity.'
              : 'Registry unavailable (no internet connection from container).'}
          </div>
        ) : null}
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search registry..."
          disabled={!registryOnline}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
        />
        {registryQuery.data?.servers?.length ? (
          <div className="max-h-64 overflow-auto border border-gray-200 rounded-lg">
            {registryQuery.data.servers.map((server: any) => {
              const name = getRegistryName(server)
              const id = getRegistryId(server)
              const description = getRegistryDescription(server)
              const isSelected = selectedServer?.id === id
              const isSelectable = Boolean(name && id)
              return (
              <button
                key={id || name || JSON.stringify(server)}
                onClick={() => {
                  if (!isSelectable) return
                  setSelectedServer({ id, name })
                  if (!namespace.trim()) {
                    setNamespace(suggestNamespace(name))
                  }
                }}
                disabled={!isSelectable}
                className={`w-full text-left px-3 py-2 border-b border-gray-100 hover:bg-gray-50 ${
                  isSelected ? 'bg-primary-50' : ''
                } ${!isSelectable ? 'cursor-not-allowed opacity-60' : ''}`}
              >
                <div className="font-medium text-gray-800">{name || 'Unknown server'}</div>
                <div className="text-xs text-gray-500">{description}</div>
              </button>
              )
            })}
          </div>
        ) : search.trim().length >= 2 ? (
          <div className="text-sm text-gray-500">No results.</div>
        ) : null}
      </div>

      <div className={`bg-white rounded-xl shadow-sm border border-gray-200 p-4 space-y-3 ${registryOnline ? '' : 'opacity-60'}`}>
        <div className="text-xs text-gray-400 uppercase tracking-wide">Install</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <input
            type="text"
            value={selectedServer?.name || ''}
            readOnly
            placeholder="Select a registry server"
            className="px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-gray-700"
          />
          <input
            type="text"
            value={namespace}
            onChange={(e) => setNamespace(e.target.value)}
            placeholder="Namespace (e.g. github)"
            disabled={!registryOnline}
            className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          />
          <input
            type="text"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            placeholder="Version (optional)"
            disabled={!registryOnline}
            className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          />
        </div>
        <button
          onClick={() => addMutation.mutate()}
          disabled={!registryOnline || addMutation.isPending}
          className="px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg disabled:opacity-50"
        >
          {addMutation.isPending ? 'Installing...' : 'Install'}
        </button>
        {addMutation.error ? (
          <div className="text-sm text-red-600">{(addMutation.error as Error).message}</div>
        ) : null}
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-200">
        <div className="p-4 border-b border-gray-200">
          <div className="text-xs text-gray-400 uppercase tracking-wide">Installed Servers</div>
        </div>
        <div className="divide-y divide-gray-100">
          {serversQuery.data?.length ? (
            serversQuery.data.map((server) => (
              <div key={server.id} className="p-4 flex items-center gap-4">
                <div className="flex-1">
                  <div className="font-medium text-gray-800">{server.namespace}</div>
                  <div className="text-xs text-gray-500">{server.server_name}</div>
                  <div className="text-xs text-gray-500">Status: {server.status}</div>
                  {server.last_error ? (
                    <div className="text-xs text-red-600">{server.last_error}</div>
                  ) : null}
                </div>
                <div className="flex items-center gap-2">
                  {server.status === 'running' ? (
                    <button
                      onClick={() => stopMutation.mutate(server.id)}
                      className="px-3 py-1.5 text-sm rounded-lg border border-gray-300 hover:bg-gray-50"
                    >
                      Stop
                    </button>
                  ) : (
                    <button
                      onClick={() => startMutation.mutate(server.id)}
                      className="px-3 py-1.5 text-sm rounded-lg bg-primary-600 text-white hover:bg-primary-700"
                    >
                      Start
                    </button>
                  )}
                  <button
                    onClick={() => deleteMutation.mutate(server.id)}
                    className="px-3 py-1.5 text-sm rounded-lg border border-red-300 text-red-600 hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))
          ) : (
            <div className="p-4 text-sm text-gray-500">No servers installed.</div>
          )}
        </div>
      </div>
    </div>
  )
}

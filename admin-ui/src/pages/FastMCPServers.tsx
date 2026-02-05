import { useState, useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import CodeMirror from '@uiw/react-codemirror'
import { yaml } from '@codemirror/lang-yaml'
import { json } from '@codemirror/lang-json'
import {
  addFastMcpServer,
  addManualFastMcpServer,
  checkRegistryHealth,
  deleteFastMcpServer,
  getFastMcpServer,
  getFastMcpServerConfig,
  listFastMcpServers,
  listFastMcpServerConfigFiles,
  searchRegistryServers,
  startFastMcpServer,
  stopFastMcpServer,
  updateFastMcpServer,
  updateFastMcpServerConfig,
  FastMCPServer,
  FastMCPConfigFileInfo,
} from '../api/client'
import {
  X,
  ChevronRight,
  Play,
  Square,
  Trash2,
  Save,
  RefreshCw,
  Server,
  FileCode,
  Terminal,
  Plus,
} from 'lucide-react'

type TabType = 'registry' | 'manual'

export default function FastMCPServers() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabType>('registry')
  const [search, setSearch] = useState('')
  const [namespace, setNamespace] = useState('')
  const [version, setVersion] = useState('')
  const [selectedServer, setSelectedServer] = useState<{ id: string | null; name: string } | null>(null)

  // Manual server form state
  const [manualNamespace, setManualNamespace] = useState('')
  const [manualServerName, setManualServerName] = useState('')
  const [manualCommand, setManualCommand] = useState('')
  const [manualArgs, setManualArgs] = useState('')
  const [manualEnv, setManualEnv] = useState('')

  // Server detail panel state
  const [detailServerId, setDetailServerId] = useState<number | null>(null)
  const [editCommand, setEditCommand] = useState('')
  const [editArgs, setEditArgs] = useState('')
  const [editEnv, setEditEnv] = useState('')
  const [configContent, setConfigContent] = useState('')
  const [configFilename, setConfigFilename] = useState('config.yaml')
  const [configFiles, setConfigFiles] = useState<FastMCPConfigFileInfo[]>([])
  const [configDirty, setConfigDirty] = useState(false)

  const suggestNamespace = (serverName: string): string => {
    const raw = serverName.split('/').pop() || serverName
    let slug = raw.toLowerCase().replace(/[^a-z0-9_-]+/g, '-')
    slug = slug.replace(/^-+|-+$/g, '')
    if (!slug) slug = 'namespace'
    if (!/^[a-z]/.test(slug)) slug = `ns-${slug}`
    return slug
  }

  const getRegistryName = (server: any): string => {
    return server?.name || server?.server?.name || server?.id || ''
  }

  const getRegistryId = (server: any): string => {
    return server?.id || server?.server?.id || ''
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

  // Server detail query
  const serverDetailQuery = useQuery({
    queryKey: ['fastmcpServerDetail', detailServerId],
    queryFn: () => getFastMcpServer(detailServerId!),
    enabled: detailServerId !== null,
  })

  // Config files list query
  const configFilesQuery = useQuery({
    queryKey: ['fastmcpConfigFiles', detailServerId],
    queryFn: () => listFastMcpServerConfigFiles(detailServerId!),
    enabled: detailServerId !== null,
  })

  // Config content query
  const configContentQuery = useQuery({
    queryKey: ['fastmcpConfig', detailServerId, configFilename],
    queryFn: () => getFastMcpServerConfig(detailServerId!, configFilename),
    enabled: detailServerId !== null && configFilename !== '',
  })

  // Update form fields when server detail loads
  useEffect(() => {
    if (serverDetailQuery.data) {
      const server = serverDetailQuery.data
      setEditCommand(server.command || '')
      setEditArgs(server.args?.join(' ') || '')
      setEditEnv(
        server.env
          ? Object.entries(server.env)
              .map(([k, v]) => `${k}=${v}`)
              .join('\n')
          : ''
      )
    }
  }, [serverDetailQuery.data])

  // Update config files list
  useEffect(() => {
    if (configFilesQuery.data) {
      setConfigFiles(configFilesQuery.data.files)
      if (configFilesQuery.data.files.length > 0 && !configFilename) {
        setConfigFilename(configFilesQuery.data.files[0].filename)
      }
    }
  }, [configFilesQuery.data])

  // Update config content
  useEffect(() => {
    if (configContentQuery.data) {
      setConfigContent(configContentQuery.data.content)
      setConfigDirty(false)
    }
  }, [configContentQuery.data])

  const addMutation = useMutation({
    mutationFn: () => {
      if (!selectedServer || !namespace) {
        throw new Error('Select a server and enter a namespace')
      }
      return addFastMcpServer(selectedServer.id || null, selectedServer.name, namespace, version || undefined)
    },
    onSuccess: (data) => {
      setNamespace('')
      setVersion('')
      setSelectedServer(null)
      queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] })
      queryClient.invalidateQueries({ queryKey: ['allNamespaces'] })
      // Auto-open detail panel so user can review pre-filled config before starting
      if (data?.id) {
        setDetailServerId(data.id)
      }
    },
  })

  const addManualMutation = useMutation({
    mutationFn: () => {
      if (!manualNamespace || !manualServerName || !manualCommand) {
        throw new Error('Namespace, server name, and command are required')
      }
      return addManualFastMcpServer({
        namespace: manualNamespace,
        server_name: manualServerName,
        command: manualCommand,
        args: manualArgs.trim() ? manualArgs.split(/\s+/) : undefined,
        env: manualEnv.trim()
          ? Object.fromEntries(
              manualEnv.split('\n').map((line) => {
                const [key, ...val] = line.split('=')
                return [key.trim(), val.join('=').trim()]
              })
            )
          : undefined,
      })
    },
    onSuccess: () => {
      setManualNamespace('')
      setManualServerName('')
      setManualCommand('')
      setManualArgs('')
      setManualEnv('')
      queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] })
      queryClient.invalidateQueries({ queryKey: ['allNamespaces'] })
    },
  })

  const updateServerMutation = useMutation({
    mutationFn: (data: { id: number; command?: string; args?: string[]; env?: Record<string, string> }) =>
      updateFastMcpServer(data.id, {
        command: data.command,
        args: data.args,
        env: data.env,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] })
      queryClient.invalidateQueries({ queryKey: ['fastmcpServerDetail', detailServerId] })
    },
  })

  const updateConfigMutation = useMutation({
    mutationFn: (data: { id: number; content: string; filename: string }) =>
      updateFastMcpServerConfig(data.id, data.content, data.filename),
    onSuccess: () => {
      setConfigDirty(false)
      queryClient.invalidateQueries({ queryKey: ['fastmcpConfig', detailServerId, configFilename] })
    },
  })

  const startMutation = useMutation({
    mutationFn: (id: number) => startFastMcpServer(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] })
      queryClient.invalidateQueries({ queryKey: ['allNamespaces'] })
      queryClient.invalidateQueries({ queryKey: ['fastmcpServerDetail', detailServerId] })
    },
  })

  const stopMutation = useMutation({
    mutationFn: (id: number) => stopFastMcpServer(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] })
      queryClient.invalidateQueries({ queryKey: ['allNamespaces'] })
      queryClient.invalidateQueries({ queryKey: ['fastmcpServerDetail', detailServerId] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteFastMcpServer(id),
    onSuccess: (_data, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] })
      queryClient.invalidateQueries({ queryKey: ['allNamespaces'] })
      if (detailServerId === deletedId) {
        setDetailServerId(null)
      }
    },
  })

  const handleSaveServer = () => {
    if (!detailServerId) return

    const args = editArgs.trim() ? editArgs.split(/\s+/) : undefined
    const env = editEnv.trim()
      ? Object.fromEntries(
          editEnv.split('\n').map((line) => {
            const [key, ...val] = line.split('=')
            return [key.trim(), val.join('=').trim()]
          })
        )
      : undefined

    updateServerMutation.mutate({
      id: detailServerId,
      command: editCommand || undefined,
      args,
      env,
    })
  }

  const handleSaveConfig = () => {
    if (!detailServerId) return
    updateConfigMutation.mutate({
      id: detailServerId,
      content: configContent,
      filename: configFilename,
    })
  }

  const openServerDetail = (server: FastMCPServer) => {
    setDetailServerId(server.id)
    setConfigFilename(server.config_path?.split('/').pop() || 'config.yaml')
  }

  const closeServerDetail = () => {
    setDetailServerId(null)
    setConfigContent('')
    setConfigFiles([])
    setConfigDirty(false)
  }

  const detailServer = serverDetailQuery.data

  return (
    <div className="h-[calc(100vh-3rem)] flex">
      {/* Main Content */}
      <div className={`flex-1 overflow-auto p-6 space-y-6 ${detailServerId ? 'mr-[480px]' : ''}`}>
        <div>
          <h1 className="text-2xl font-bold text-gray-900">External MCP Servers</h1>
          <p className="text-gray-600 text-sm">Install from the MCP Registry or add manual servers.</p>
        </div>

        {/* Tab Selector */}
        <div className="flex gap-2">
          <button
            onClick={() => setActiveTab('registry')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'registry'
                ? 'bg-primary-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            From Registry
          </button>
          <button
            onClick={() => setActiveTab('manual')}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              activeTab === 'manual'
                ? 'bg-primary-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            Manual Server
          </button>
        </div>

        {/* Registry Tab */}
        {activeTab === 'registry' && (
          <>
            <div
              className={`bg-white rounded-xl shadow-sm border border-gray-200 p-4 space-y-3 ${
                registryOnline ? '' : 'opacity-60'
              }`}
            >
              <div className="text-xs text-gray-400 uppercase tracking-wide">Registry Search</div>
              <div className="text-xs text-gray-500">
                Showing installable servers only (PyPI, npm, or repo-based).
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
                    const isSelectable = Boolean(name)
                    return (
                      <button
                        key={id || name || JSON.stringify(server)}
                        onClick={() => {
                          if (!isSelectable) return
                          setSelectedServer({ id: id || null, name })
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

            <div
              className={`bg-white rounded-xl shadow-sm border border-gray-200 p-4 space-y-3 ${
                registryOnline ? '' : 'opacity-60'
              }`}
            >
              <div className="text-xs text-gray-400 uppercase tracking-wide">Install from Registry</div>
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
          </>
        )}

        {/* Manual Tab */}
        {activeTab === 'manual' && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 space-y-4">
            <div className="text-xs text-gray-400 uppercase tracking-wide">Add Manual MCP Server</div>
            <p className="text-sm text-gray-600">
              Add a server using Claude Desktop config format (command, args, env).
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Namespace</label>
                <input
                  type="text"
                  value={manualNamespace}
                  onChange={(e) => setManualNamespace(e.target.value)}
                  placeholder="e.g. my-server"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Server Name</label>
                <input
                  type="text"
                  value={manualServerName}
                  onChange={(e) => setManualServerName(e.target.value)}
                  placeholder="Display name"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Command</label>
              <input
                type="text"
                value={manualCommand}
                onChange={(e) => setManualCommand(e.target.value)}
                placeholder="e.g. python, node, npx"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Arguments (space-separated)</label>
              <input
                type="text"
                value={manualArgs}
                onChange={(e) => setManualArgs(e.target.value)}
                placeholder="e.g. -m my_module --config config.yaml"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Environment Variables (one per line: KEY=value)
              </label>
              <textarea
                value={manualEnv}
                onChange={(e) => setManualEnv(e.target.value)}
                placeholder="API_KEY=xxx&#10;DEBUG=true"
                rows={3}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none font-mono text-sm"
              />
            </div>

            <button
              onClick={() => addManualMutation.mutate()}
              disabled={addManualMutation.isPending || !manualNamespace || !manualServerName || !manualCommand}
              className="flex items-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg disabled:opacity-50"
            >
              <Plus className="w-4 h-4" />
              {addManualMutation.isPending ? 'Adding...' : 'Add Server'}
            </button>
            {addManualMutation.error ? (
              <div className="text-sm text-red-600">{(addManualMutation.error as Error).message}</div>
            ) : null}
          </div>
        )}

        {/* Installed Servers List */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200">
          <div className="p-4 border-b border-gray-200 flex items-center justify-between">
            <div className="text-xs text-gray-400 uppercase tracking-wide">Installed Servers</div>
            <button
              onClick={() => queryClient.invalidateQueries({ queryKey: ['fastmcpServers'] })}
              className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
          </div>
          <div className="divide-y divide-gray-100">
            {serversQuery.data?.length ? (
              serversQuery.data.map((server) => (
                <div
                  key={server.id}
                  className={`p-4 flex items-center gap-4 cursor-pointer hover:bg-gray-50 ${
                    detailServerId === server.id ? 'bg-primary-50' : ''
                  }`}
                  onClick={() => openServerDetail(server)}
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <Server className="w-4 h-4 text-gray-400" />
                      <span className="font-medium text-gray-800">{server.namespace}</span>
                      <span
                        className={`text-xs px-1.5 py-0.5 rounded ${
                          server.status === 'running'
                            ? 'bg-green-100 text-green-700'
                            : server.status === 'error'
                            ? 'bg-red-100 text-red-700'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {server.status}
                      </span>
                      <span className="text-xs text-gray-400">{server.install_method}</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-1">{server.server_name}</div>
                    {server.last_error ? (
                      <div className="text-xs text-red-600 mt-1">{server.last_error}</div>
                    ) : null}
                  </div>
                  <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                    {server.status === 'running' ? (
                      <button
                        onClick={() => stopMutation.mutate(server.id)}
                        className="p-2 text-gray-600 hover:text-orange-600 hover:bg-orange-50 rounded-lg transition-colors"
                        title="Stop server"
                      >
                        <Square className="w-4 h-4" />
                      </button>
                    ) : (
                      <button
                        onClick={() => startMutation.mutate(server.id)}
                        className="p-2 text-gray-600 hover:text-green-600 hover:bg-green-50 rounded-lg transition-colors"
                        title="Start server"
                      >
                        <Play className="w-4 h-4" />
                      </button>
                    )}
                    <button
                      onClick={() => deleteMutation.mutate(server.id)}
                      className="p-2 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      title="Delete server"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                    <ChevronRight className="w-4 h-4 text-gray-400" />
                  </div>
                </div>
              ))
            ) : (
              <div className="p-4 text-sm text-gray-500">No servers installed.</div>
            )}
          </div>
        </div>
      </div>

      {/* Server Detail Panel */}
      {detailServerId && (
        <div className="fixed right-0 top-12 bottom-0 w-[480px] bg-white border-l border-gray-200 shadow-lg flex flex-col">
          {/* Header */}
          <div className="p-4 border-b border-gray-200 flex items-center justify-between">
            <div>
              <h2 className="font-semibold text-gray-900">{detailServer?.namespace || 'Loading...'}</h2>
              <p className="text-sm text-gray-500">{detailServer?.server_name}</p>
            </div>
            <button
              onClick={closeServerDetail}
              className="p-2 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-auto p-4 space-y-6">
            {serverDetailQuery.isLoading ? (
              <div className="text-sm text-gray-500">Loading...</div>
            ) : serverDetailQuery.error ? (
              <div className="text-sm text-red-600">Error loading server details</div>
            ) : detailServer ? (
              <>
                {/* Server Info */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
                    <Server className="w-4 h-4" />
                    Server Info
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div className="text-gray-500">Status:</div>
                    <div
                      className={
                        detailServer.status === 'running'
                          ? 'text-green-600'
                          : detailServer.status === 'error'
                          ? 'text-red-600'
                          : 'text-gray-600'
                      }
                    >
                      {detailServer.status}
                    </div>
                    <div className="text-gray-500">Install Method:</div>
                    <div className="text-gray-900">{detailServer.install_method}</div>
                    {detailServer.pid && (
                      <>
                        <div className="text-gray-500">PID:</div>
                        <div className="text-gray-900">{detailServer.pid}</div>
                      </>
                    )}
                    {detailServer.port && (
                      <>
                        <div className="text-gray-500">Port:</div>
                        <div className="text-gray-900">{detailServer.port}</div>
                      </>
                    )}
                  </div>
                </div>

                {/* Command Configuration */}
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
                    <Terminal className="w-4 h-4" />
                    Start Command
                  </div>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Command</label>
                    <input
                      type="text"
                      value={editCommand}
                      onChange={(e) => setEditCommand(e.target.value)}
                      placeholder="e.g. python, node, npx"
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none font-mono"
                    />
                  </div>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Arguments (space-separated)</label>
                    <input
                      type="text"
                      value={editArgs}
                      onChange={(e) => setEditArgs(e.target.value)}
                      placeholder="e.g. -m my_module --config config.yaml"
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none font-mono"
                    />
                  </div>

                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Environment Variables</label>
                    <textarea
                      value={editEnv}
                      onChange={(e) => setEditEnv(e.target.value)}
                      placeholder="KEY=value (one per line)"
                      rows={3}
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none font-mono"
                    />
                  </div>

                  <button
                    onClick={handleSaveServer}
                    disabled={updateServerMutation.isPending}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary-600 hover:bg-primary-700 text-white rounded-lg disabled:opacity-50"
                  >
                    <Save className="w-4 h-4" />
                    {updateServerMutation.isPending ? 'Saving...' : 'Save Command'}
                  </button>
                  {updateServerMutation.error ? (
                    <div className="text-xs text-red-600">
                      {(updateServerMutation.error as Error).message}
                    </div>
                  ) : updateServerMutation.isSuccess ? (
                    <div className="text-xs text-green-600">Saved!</div>
                  ) : null}
                </div>

                {/* Config File Editor */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
                      <FileCode className="w-4 h-4" />
                      Config File
                    </div>
                    {configFiles.length > 0 && (
                      <select
                        value={configFilename}
                        onChange={(e) => {
                          setConfigFilename(e.target.value)
                          setConfigDirty(false)
                        }}
                        className="text-xs border border-gray-300 rounded px-2 py-1"
                      >
                        {configFiles.map((f) => (
                          <option key={f.filename} value={f.filename}>
                            {f.filename}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>

                  <div className="border border-gray-200 rounded-lg overflow-hidden">
                    <CodeMirror
                      value={configContent}
                      onChange={(value) => {
                        setConfigContent(value)
                        setConfigDirty(true)
                      }}
                      extensions={[
                        configFilename.endsWith('.json') ? json() : yaml(),
                      ]}
                      theme="light"
                      height="200px"
                      basicSetup={{
                        lineNumbers: true,
                        foldGutter: true,
                      }}
                    />
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleSaveConfig}
                      disabled={updateConfigMutation.isPending || !configDirty}
                      className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary-600 hover:bg-primary-700 text-white rounded-lg disabled:opacity-50"
                    >
                      <Save className="w-4 h-4" />
                      {updateConfigMutation.isPending ? 'Saving...' : 'Save Config'}
                    </button>
                    {configDirty && (
                      <span className="text-xs text-yellow-600">Unsaved changes</span>
                    )}
                    {updateConfigMutation.isSuccess && !configDirty && (
                      <span className="text-xs text-green-600">Saved!</span>
                    )}
                  </div>
                  {updateConfigMutation.error ? (
                    <div className="text-xs text-red-600">
                      {(updateConfigMutation.error as Error).message}
                    </div>
                  ) : null}
                </div>

                {/* Last Error */}
                {detailServer.last_error && (
                  <div className="space-y-2">
                    <div className="text-sm font-medium text-red-600">Last Error</div>
                    <pre className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-800 whitespace-pre-wrap overflow-auto max-h-40">
                      {detailServer.last_error}
                    </pre>
                  </div>
                )}
              </>
            ) : null}
          </div>

          {/* Footer Actions */}
          <div className="p-4 border-t border-gray-200 flex items-center gap-2">
            {detailServer?.status === 'running' ? (
              <button
                onClick={() => stopMutation.mutate(detailServerId)}
                disabled={stopMutation.isPending}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 text-sm border border-orange-300 text-orange-600 hover:bg-orange-50 rounded-lg"
              >
                <Square className="w-4 h-4" />
                Stop Server
              </button>
            ) : (
              <button
                onClick={() => startMutation.mutate(detailServerId)}
                disabled={startMutation.isPending}
                className="flex-1 flex items-center justify-center gap-2 px-4 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg"
              >
                <Play className="w-4 h-4" />
                Start Server
              </button>
            )}
            <button
              onClick={() => {
                deleteMutation.mutate(detailServerId)
              }}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 text-sm border border-red-300 text-red-600 hover:bg-red-50 rounded-lg"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

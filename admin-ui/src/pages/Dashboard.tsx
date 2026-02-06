import { useQuery } from '@tanstack/react-query'
import {
  getSystemHealth,
  getSystemInfo,
  getSystemMetrics,
  getNamespaces,
  listFastMcpServers,
} from '../api/client'
import {
  CheckCircle,
  XCircle,
  AlertCircle,
  Server,
  Folder,
  Wrench,
} from 'lucide-react'

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'healthy':
      return <CheckCircle className="w-5 h-5 text-green-500" />
    case 'degraded':
      return <AlertCircle className="w-5 h-5 text-yellow-500" />
    default:
      return <XCircle className="w-5 h-5 text-red-500" />
  }
}

export default function Dashboard() {
  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: getSystemHealth,
    refetchInterval: 10000, // Refresh every 10 seconds
  })

  const infoQuery = useQuery({
    queryKey: ['info'],
    queryFn: getSystemInfo,
  })

  const namespacesQuery = useQuery({
    queryKey: ['namespaces'],
    queryFn: getNamespaces,
  })

  const fastmcpServersQuery = useQuery({
    queryKey: ['fastmcpServers'],
    queryFn: listFastMcpServers,
  })

  const metricsQuery = useQuery({
    queryKey: ['metrics'],
    queryFn: getSystemMetrics,
    refetchInterval: 10000,
  })

  const formatRate = (rate: number) => `${rate.toFixed(1)}%`

  const serviceOrder = ['openapi', 'mcp', 'web']
  const serviceLabels: Record<string, string> = {
    openapi: 'OpenAPI',
    mcp: 'MCP',
    web: 'Admin',
  }

  const toolCallWindows = [
    { key: 'last_5m', label: 'Last 5m' },
    { key: 'last_1h', label: 'Last 1h' },
    { key: 'last_24h', label: 'Last 24h' },
    { key: 'last_7d', label: 'Last 7d' },
  ] as const

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>

      {/* Health Status */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Server className="w-5 h-5" />
          System Health
        </h2>

        {healthQuery.isLoading ? (
          <div className="text-gray-500">Loading...</div>
        ) : healthQuery.error ? (
          <div className="text-red-500">Failed to load health status</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {healthQuery.data?.services.map((service) => (
              <div
                key={service.name}
                className="flex items-center justify-between p-4 bg-gray-50 rounded-lg"
              >
                <div className="flex items-center gap-3">
                  <StatusIcon status={service.status} />
                  <div className="font-medium text-gray-900 capitalize">
                    {service.name}
                  </div>
                </div>
                <div className="text-xs text-gray-500">
                  Last checked: {new Date(healthQuery.data?.timestamp || Date.now()).toLocaleTimeString()}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Tool Calls */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Tool Calls</h2>
        {metricsQuery.isLoading ? (
          <div className="text-gray-500">Loading...</div>
        ) : metricsQuery.error ? (
          <div className="text-red-500">Failed to load metrics</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {toolCallWindows.map((window) => {
              const stats = metricsQuery.data?.tool_calls?.[window.key]
              if (!stats) return null
              const successRate = stats.total ? (stats.success / stats.total) * 100 : 0
              return (
                <div key={window.key} className="p-4 bg-gray-50 rounded-lg">
                  <div className="text-sm text-gray-500">{window.label}</div>
                  <div className="text-2xl font-bold text-gray-900">{stats.total}</div>
                  <div className="text-xs text-gray-600">
                    {stats.success} ok / {stats.error} err
                  </div>
                  <div className="text-xs text-gray-500 mt-1">
                    Success {successRate.toFixed(1)}%
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Error Rate */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">
          Error Rate (by Service)
        </h2>
        {metricsQuery.isLoading ? (
          <div className="text-gray-500">Loading...</div>
        ) : metricsQuery.error ? (
          <div className="text-red-500">Failed to load metrics</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {serviceOrder.map((service) => {
              const rates = metricsQuery.data?.services?.[service]
              if (!rates) return null
              return (
                <div key={service} className="p-4 bg-gray-50 rounded-lg">
                  <div className="font-medium text-gray-900 mb-2">
                    {serviceLabels[service] || service}
                  </div>
                  <div className="space-y-1 text-xs text-gray-600">
                    <div className="flex justify-between">
                      <span>Last 5m</span>
                      <span className="font-mono">
                        {formatRate(rates.last_5m.error_rate)} ({rates.last_5m.errors}/{rates.last_5m.requests})
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Last 1h</span>
                      <span className="font-mono">
                        {formatRate(rates.last_1h.error_rate)} ({rates.last_1h.errors}/{rates.last_1h.requests})
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Last 24h</span>
                      <span className="font-mono">
                        {formatRate(rates.last_24h.error_rate)} ({rates.last_24h.errors}/{rates.last_24h.requests})
                      </span>
                    </div>
                    <div className="flex justify-between">
                      <span>Last 7d</span>
                      <span className="font-mono">
                        {formatRate(rates.last_7d.error_rate)} ({rates.last_7d.errors}/{rates.last_7d.requests})
                      </span>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Namespaces */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Folder className="w-5 h-5" />
            Namespaces
          </h2>

          {namespacesQuery.isLoading ? (
            <div className="text-gray-500">Loading...</div>
          ) : namespacesQuery.error ? (
            <div className="text-red-500">Failed to load</div>
          ) : (
            <div>
              <div className="flex items-center justify-between mb-3">
                <div className="text-3xl font-bold text-primary-600">
                  {namespacesQuery.data?.length || 0}
                </div>
                {(fastmcpServersQuery.data?.length || 0) > 0 && (
                  <div className="text-xs text-gray-500">
                    {(fastmcpServersQuery.data?.length || 0)} MCP servers
                  </div>
                )}
              </div>

              <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">Native</div>
              <div className="flex flex-wrap gap-2 mb-4">
                {namespacesQuery.data?.length ? (
                  namespacesQuery.data.map((ns) => (
                    <span
                      key={ns.name}
                      className="inline-flex items-center gap-2 px-2.5 py-1 bg-blue-50 text-blue-700 rounded-full text-xs"
                    >
                      {ns.name}
                      <span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">
                        {ns.tool_count}
                      </span>
                    </span>
                  ))
                ) : (
                  <div className="text-sm text-gray-500">No native namespaces</div>
                )}
              </div>

              <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">External</div>
              <div className="flex flex-wrap gap-2">
                {fastmcpServersQuery.data?.length ? (
                  <>
                    {fastmcpServersQuery.data?.map((server) => (
                      <span
                        key={`fastmcp-${server.id}`}
                        className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs ${
                          server.status === 'running'
                            ? 'bg-purple-50 text-purple-700'
                            : 'bg-gray-100 text-gray-500'
                        }`}
                      >
                        {server.namespace}
                        <span
                          className={`px-1.5 py-0.5 rounded-full ${
                            server.status === 'running' ? 'bg-purple-100 text-purple-700' : 'bg-gray-200 text-gray-600'
                          }`}
                        >
                          fastmcp {server.status}
                        </span>
                      </span>
                    ))}
                  </>
                ) : (
                  <div className="text-sm text-gray-500">No MCP servers</div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Environment */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Wrench className="w-5 h-5" />
            Configuration
          </h2>

          {infoQuery.isLoading ? (
            <div className="text-gray-500">Loading...</div>
          ) : infoQuery.error ? (
            <div className="text-red-500">Failed to load</div>
          ) : (
            <div className="space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Version:</span>
                <span className="font-mono">{infoQuery.data?.version}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Data Volume:</span>
                <span className="font-mono text-xs">
                  {infoQuery.data?.environment?.host_data_dir || infoQuery.data?.data_dir || 'tooldock_data'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">MCP Protocol:</span>
                <span className="font-mono text-xs">
                  {infoQuery.data?.environment?.mcp_protocol_version || '2024-11-05'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">MCP Supported:</span>
                <span className="font-mono text-xs">
                  {infoQuery.data?.environment?.mcp_protocol_versions || '2024-11-05,2025-03-26,2025-11-25'}
                </span>
              </div>

              <div className="border-t border-gray-100 pt-3 mt-3">
                <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">Ports</div>
                {Object.entries(infoQuery.data?.environment || {})
                  .filter(([key]) => key.includes('port') && !key.includes('internal'))
                  .map(([key, value]) => (
                    <div key={key} className="flex justify-between">
                      <span className="text-gray-500">{key.replace('_', ' ')}:</span>
                      <span className="font-mono">{value}</span>
                    </div>
                  ))}
              </div>

              <div className="bg-gray-50 rounded-lg p-3 mt-3">
                <p className="text-xs text-gray-500">
                  To change ports, edit <code className="bg-gray-200 px-1 rounded">.env</code> and restart with{' '}
                  <code className="bg-gray-200 px-1 rounded">docker compose restart</code>
                </p>
              </div>
            </div>
          )}
        </div>
      </div>

    </div>
  )
}

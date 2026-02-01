import { useQuery } from '@tanstack/react-query'
import { getSystemHealth, getSystemInfo } from '../api/client'
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
                className="flex items-center gap-3 p-4 bg-gray-50 rounded-lg"
              >
                <StatusIcon status={service.status} />
                <div>
                  <div className="font-medium text-gray-900 capitalize">
                    {service.name} Server
                  </div>
                  <div className="text-sm text-gray-500">
                    Port {service.port} - {service.status}
                  </div>
                </div>
              </div>
            ))}
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

          {infoQuery.isLoading ? (
            <div className="text-gray-500">Loading...</div>
          ) : infoQuery.error ? (
            <div className="text-red-500">Failed to load</div>
          ) : (
            <div>
              <div className="text-3xl font-bold text-primary-600 mb-2">
                {infoQuery.data?.namespaces.length || 0}
              </div>
              <div className="space-y-1">
                {infoQuery.data?.namespaces.map((ns) => (
                  <div key={ns} className="text-sm text-gray-600">
                    • {ns}
                  </div>
                ))}
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
                <span className="font-mono">./tooldock_data</span>
              </div>

              <div className="border-t border-gray-100 pt-3 mt-3">
                <div className="text-xs text-gray-400 uppercase tracking-wide mb-2">Ports</div>
                {Object.entries(infoQuery.data?.environment || {})
                  .filter(([key]) => key.includes('port'))
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

      {/* Quick Links */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Quick Links</h2>
        <div className="flex flex-wrap gap-3">
          <a
            href={`http://localhost:${healthQuery.data?.services.find(s => s.name === 'openapi')?.port || 8006}/docs`}
            target="_blank"
            rel="noopener noreferrer"
            className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm font-medium transition-colors"
          >
            OpenAPI Docs
          </a>
          <a
            href={`http://localhost:${healthQuery.data?.services.find(s => s.name === 'openapi')?.port || 8006}/openapi.json`}
            target="_blank"
            rel="noopener noreferrer"
            className="px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg text-sm font-medium transition-colors"
          >
            OpenAPI Schema
          </a>
        </div>
      </div>
    </div>
  )
}

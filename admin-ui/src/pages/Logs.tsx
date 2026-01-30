import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getLogs } from '../api/client'
import { RefreshCw, Filter } from 'lucide-react'

const LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR'] as const

function getLevelColor(level: string): string {
  switch (level) {
    case 'ERROR':
      return 'text-red-600 bg-red-50'
    case 'WARNING':
      return 'text-yellow-600 bg-yellow-50'
    case 'DEBUG':
      return 'text-gray-500 bg-gray-50'
    default:
      return 'text-blue-600 bg-blue-50'
  }
}

export default function Logs() {
  const [limit, setLimit] = useState(100)
  const [level, setLevel] = useState<string>('')
  const [loggerFilter, setLoggerFilter] = useState('')

  const logsQuery = useQuery({
    queryKey: ['logs', limit, level, loggerFilter],
    queryFn: () => getLogs(limit, level || undefined, loggerFilter || undefined),
    refetchInterval: 5000, // Refresh every 5 seconds
  })

  const logs = logsQuery.data?.logs || []

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Logs</h1>

        <button
          onClick={() => logsQuery.refetch()}
          disabled={logsQuery.isFetching}
          className="flex items-center gap-2 px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${logsQuery.isFetching ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4 mb-4">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-500" />
            <span className="text-sm text-gray-600">Filters:</span>
          </div>

          <select
            value={level}
            onChange={(e) => setLevel(e.target.value)}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          >
            <option value="">All Levels</option>
            {LOG_LEVELS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>

          <input
            type="text"
            value={loggerFilter}
            onChange={(e) => setLoggerFilter(e.target.value)}
            placeholder="Logger name..."
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          />

          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
          >
            <option value={50}>50 entries</option>
            <option value={100}>100 entries</option>
            <option value={250}>250 entries</option>
            <option value={500}>500 entries</option>
          </select>

          <div className="text-sm text-gray-500 ml-auto">
            Showing {logs.length} of {logsQuery.data?.total || 0} entries
            {logsQuery.data?.has_more && ' (more available)'}
          </div>
        </div>
      </div>

      {/* Log Entries */}
      <div className="flex-1 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden flex flex-col">
        <div className="flex-1 overflow-auto">
          {logsQuery.isLoading ? (
            <div className="p-4 text-gray-500">Loading...</div>
          ) : logs.length === 0 ? (
            <div className="p-4 text-gray-500 text-center">
              No log entries found
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-44">
                    Timestamp
                  </th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-24">
                    Level
                  </th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-32">
                    Logger
                  </th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">
                    Message
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {logs.map((log, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-mono text-gray-500 whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${getLevelColor(
                          log.level
                        )}`}
                      >
                        {log.level}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-600 truncate">
                      {log.logger}
                    </td>
                    <td className="px-4 py-2 font-mono text-gray-900 whitespace-pre-wrap">
                      {log.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

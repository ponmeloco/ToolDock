import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getLogs } from '../api/client'
import { RefreshCw, Filter, Clock, Globe, Terminal, Wrench, ChevronDown, ChevronRight, AlertCircle } from 'lucide-react'

type TabType = 'all' | 'http' | 'tools'

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

function getStatusColor(status: number): string {
  if (status >= 500) {
    return 'text-red-600 bg-red-100 border-red-200'
  } else if (status >= 400) {
    return 'text-yellow-600 bg-yellow-100 border-yellow-200'
  } else if (status >= 300) {
    return 'text-blue-600 bg-blue-100 border-blue-200'
  } else if (status >= 200) {
    return 'text-green-600 bg-green-100 border-green-200'
  }
  return 'text-gray-600 bg-gray-100 border-gray-200'
}

function getMethodColor(method: string): string {
  switch (method) {
    case 'GET':
      return 'text-green-700 bg-green-50'
    case 'POST':
      return 'text-blue-700 bg-blue-50'
    case 'PUT':
      return 'text-yellow-700 bg-yellow-50'
    case 'DELETE':
      return 'text-red-700 bg-red-50'
    default:
      return 'text-gray-700 bg-gray-50'
  }
}

export default function Logs() {
  const [limit, setLimit] = useState(100)
  const [level, setLevel] = useState<string>('')
  const [loggerFilter, setLoggerFilter] = useState('')
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [activeTab, setActiveTab] = useState<TabType>('tools')
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set())

  const toggleRow = (index: number) => {
    const newExpanded = new Set(expandedRows)
    if (newExpanded.has(index)) {
      newExpanded.delete(index)
    } else {
      newExpanded.add(index)
    }
    setExpandedRows(newExpanded)
  }

  const logsQuery = useQuery({
    queryKey: ['logs', limit, level, loggerFilter],
    queryFn: () => getLogs(limit, level || undefined, loggerFilter || undefined),
    refetchInterval: 5000,
  })

  useEffect(() => {
    if (logsQuery.dataUpdatedAt) {
      setLastUpdated(new Date(logsQuery.dataUpdatedAt))
    }
  }, [logsQuery.dataUpdatedAt])

  const allLogs = logsQuery.data?.logs || []

  // Filter logs based on active tab
  const logs = allLogs.filter((log) => {
    if (activeTab === 'http') {
      if (log.http_status === undefined || log.http_status === null) return false
      if (log.http_path?.endsWith('/health')) return false
      return true
    } else if (activeTab === 'tools') {
      return log.tool_name !== undefined && log.tool_name !== null
    }
    return true
  })

  // Count for tabs
  const httpCount = allLogs.filter(
    (l) => l.http_status !== undefined && l.http_status !== null && !l.http_path?.endsWith('/health')
  ).length
  const toolCount = allLogs.filter((l) => l.tool_name !== undefined && l.tool_name !== null).length

  const tabs = [
    { id: 'http' as TabType, label: 'HTTP Requests', icon: Globe, count: httpCount },
    { id: 'tools' as TabType, label: 'Tool Calls', icon: Wrench, count: toolCount },
    { id: 'all' as TabType, label: 'All Logs', icon: Terminal, count: allLogs.length },
  ]

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-bold text-gray-900">Logs</h1>

        <div className="flex items-center gap-4">
          {lastUpdated && (
            <div className="flex items-center gap-1.5 text-sm text-gray-500">
              <Clock className="w-4 h-4" />
              <span>Updated: {lastUpdated.toLocaleTimeString()}</span>
              {logsQuery.isFetching && <span className="text-primary-600">(refreshing...)</span>}
            </div>
          )}
          <button
            onClick={() => logsQuery.refetch()}
            disabled={logsQuery.isFetching}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${logsQuery.isFetching ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-4 bg-gray-100 p-1 rounded-lg w-fit">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md transition-colors ${
              activeTab === tab.id
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
            <span
              className={`px-1.5 py-0.5 text-xs rounded-full ${
                activeTab === tab.id ? 'bg-primary-100 text-primary-700' : 'bg-gray-200 text-gray-600'
              }`}
            >
              {tab.count}
            </span>
          </button>
        ))}
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
            Showing {logs.length} entries
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
            <div className="p-4 text-gray-500 text-center">No log entries found</div>
          ) : activeTab === 'http' || activeTab === 'tools' ? (
            // HTTP/Tool specific view with status codes
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-28">Time</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-20">Request</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-20">Method</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-20">Status</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">Path</th>
                  {activeTab === 'tools' && (
                    <th className="px-4 py-2 text-left font-medium text-gray-600 w-36">Tool</th>
                  )}
                  <th className="px-4 py-2 text-right font-medium text-gray-600 w-24">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {logs.map((log, i) => {
                  const hasError = log.error_detail && (log.http_status || 0) >= 400
                  const isExpanded = expandedRows.has(i)
                  return (
                    <tr
                      key={i}
                      className={`hover:bg-gray-50 ${hasError ? 'cursor-pointer' : ''}`}
                      onClick={() => hasError && toggleRow(i)}
                    >
                      <td className="px-4 py-2 font-mono text-gray-500 text-xs whitespace-nowrap">
                        <div className="flex items-center gap-1">
                          {hasError && (
                            isExpanded ? (
                              <ChevronDown className="w-3 h-3 text-red-500" />
                            ) : (
                              <ChevronRight className="w-3 h-3 text-red-500" />
                            )
                          )}
                          {new Date(log.timestamp).toLocaleTimeString()}
                        </div>
                        {isExpanded && log.error_detail && (
                          <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs text-red-700 whitespace-pre-wrap font-mono max-w-lg">
                            <div className="flex items-center gap-1 mb-1 font-medium">
                              <AlertCircle className="w-3 h-3" />
                              Error Detail:
                            </div>
                            {log.error_detail}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        {log.request_id && (
                          <span className="px-1.5 py-0.5 rounded text-xs font-mono bg-gray-100 text-gray-600">
                            {log.request_id}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2">
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-medium ${getMethodColor(
                            log.http_method || ''
                          )}`}
                        >
                          {log.http_method}
                        </span>
                      </td>
                      <td className="px-4 py-2">
                        <div className="flex items-center gap-1">
                          <span
                            className={`px-2 py-0.5 rounded text-xs font-bold border ${getStatusColor(
                              log.http_status || 0
                            )}`}
                          >
                            {log.http_status}
                          </span>
                          {hasError && !isExpanded && (
                            <AlertCircle className="w-3 h-3 text-red-500" />
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-2 font-mono text-gray-700 truncate max-w-md" title={log.http_path}>
                        {log.http_path}
                      </td>
                      {activeTab === 'tools' && (
                        <td className="px-4 py-2">
                          <span className="px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-700">
                            {log.tool_name}
                          </span>
                        </td>
                      )}
                      <td className="px-4 py-2 text-right font-mono text-gray-500 text-xs">
                        {log.http_duration_ms?.toFixed(1)}ms
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          ) : (
            // All logs view
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-28">Time</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-24">Level</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600 w-32">Logger</th>
                  <th className="px-4 py-2 text-left font-medium text-gray-600">Message</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {logs.map((log, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-mono text-gray-500 text-xs whitespace-nowrap">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={`px-2 py-0.5 rounded text-xs font-medium ${getLevelColor(log.level)}`}
                      >
                        {log.level}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-gray-600 truncate text-xs">{log.logger}</td>
                    <td className="px-4 py-2 font-mono text-gray-900 text-xs whitespace-pre-wrap">
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

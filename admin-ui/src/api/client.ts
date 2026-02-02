// API Client for ToolDock Backend

const API_BASE = '/api'
const TOOLS_BASE = '/tools'

// Get auth token from localStorage or prompt
function getAuthToken(): string {
  let token = localStorage.getItem('tooldock_token')
  if (!token) {
    token = prompt('Enter your Bearer Token:') || ''
    if (token) {
      localStorage.setItem('tooldock_token', token)
    }
  }
  return token
}

// Clear auth token (for logout)
export function clearAuthToken(): void {
  localStorage.removeItem('tooldock_token')
}

// Fetch wrapper with auth
async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  const token = getAuthToken()

  const headers = new Headers(options.headers)
  headers.set('Authorization', `Bearer ${token}`)

  if (options.body && typeof options.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(url, {
    ...options,
    headers,
  })

  if (response.status === 401) {
    clearAuthToken()
    throw new Error('Unauthorized - please refresh and enter a valid token')
  }

  return response
}

// Types
export interface Namespace {
  name: string
  tool_count: number
  path: string
}

export interface Tool {
  filename: string
  namespace: string
  path: string
  size: number
}

export interface ExternalServerInfo {
  server_id: string
  namespace: string
  endpoint: string
  config: Record<string, unknown>
  enabled: boolean
}

export interface ExternalServerList {
  servers: ExternalServerInfo[]
  total: number
}

export interface ToolContent {
  filename: string
  namespace: string
  size: number
  content: string
  validation: ValidationResult
}

export interface ValidationResult {
  is_valid: boolean
  errors: string[]
  warnings: string[]
  info: Record<string, unknown>
}

export interface ServiceHealth {
  name: string
  status: string
  port: number
  details: Record<string, unknown> | null
}

export interface SystemHealth {
  status: string
  timestamp: string
  services: ServiceHealth[]
  environment: Record<string, string>
}

export interface ErrorRateWindow {
  requests: number
  errors: number
  error_rate: number
}

export interface ServiceErrorRates {
  last_5m: ErrorRateWindow
  last_1h: ErrorRateWindow
  last_24h: ErrorRateWindow
  last_7d: ErrorRateWindow
}

export interface ToolCallCounts {
  total: number
  success: number
  error: number
}

export interface ToolCallStats {
  last_5m: ToolCallCounts
  last_1h: ToolCallCounts
  last_24h: ToolCallCounts
  last_7d: ToolCallCounts
}

export interface SystemMetrics {
  timestamp: string
  services: Record<string, ServiceErrorRates>
  tool_calls: ToolCallStats
}

export interface LogEntry {
  timestamp: string
  level: string
  logger: string
  message: string
  // Optional HTTP request fields
  http_method?: string
  http_path?: string
  http_status?: number
  http_duration_ms?: number
  tool_name?: string
  service_name?: string
  request_id?: string
  error_detail?: string
}

export interface ToolExecutionResult {
  tool: string
  result: unknown
}

// API Functions

// Namespaces
export async function getNamespaces(): Promise<Namespace[]> {
  const res = await fetchWithAuth(`${API_BASE}/folders`)
  const data = await res.json()
  return data.folders || []
}

export async function createNamespace(name: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/folders`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to create namespace')
  }
}

export async function deleteNamespace(name: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/folders/${name}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to delete namespace')
  }
}

// Tools
export async function getTools(namespace: string): Promise<Tool[]> {
  const res = await fetchWithAuth(`${API_BASE}/folders/${namespace}/tools`)
  const data = await res.json()
  return data.tools || []
}

export async function getExternalServers(): Promise<ExternalServerList> {
  const res = await fetchWithAuth(`${API_BASE}/servers`)
  return res.json()
}

export async function getTool(namespace: string, filename: string): Promise<ToolContent> {
  const res = await fetchWithAuth(`${API_BASE}/folders/${namespace}/tools/${filename}`)
  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to get tool')
  }
  return res.json()
}

export async function updateTool(
  namespace: string,
  filename: string,
  content: string,
  skipValidation = false
): Promise<{ success: boolean; message: string; validation: ValidationResult }> {
  const res = await fetchWithAuth(`${API_BASE}/folders/${namespace}/tools/${filename}`, {
    method: 'PUT',
    body: JSON.stringify({ content, skip_validation: skipValidation }),
  })
  return res.json()
}

export async function uploadTool(
  namespace: string,
  file: File,
  skipValidation = false
): Promise<{ success: boolean; message: string; validation: ValidationResult }> {
  const formData = new FormData()
  formData.append('file', file)

  const token = getAuthToken()
  const res = await fetch(
    `${API_BASE}/folders/${namespace}/tools?skip_validation=${skipValidation}`,
    {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    }
  )
  return res.json()
}

export async function deleteTool(namespace: string, filename: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/folders/${namespace}/tools/${filename}`, {
    method: 'DELETE',
  })
  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to delete tool')
  }
}

export async function createToolFromTemplate(
  namespace: string,
  name: string
): Promise<{ success: boolean; message: string; filename: string; path: string }> {
  const res = await fetchWithAuth(`${API_BASE}/folders/${namespace}/tools/create-from-template`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  })
  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Failed to create tool')
  }
  return res.json()
}

export async function validateTool(
  namespace: string,
  content: string,
  filename: string
): Promise<ValidationResult> {
  const blob = new Blob([content], { type: 'text/plain' })
  const file = new File([blob], filename)
  const formData = new FormData()
  formData.append('file', file)

  const token = getAuthToken()
  const res = await fetch(`${API_BASE}/folders/${namespace}/tools/validate`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  })
  return res.json()
}

// Admin
export async function getSystemHealth(): Promise<SystemHealth> {
  const res = await fetchWithAuth(`${API_BASE}/admin/health`)
  return res.json()
}

export async function getLogs(
  limit = 100,
  level?: string,
  loggerName?: string
): Promise<{ logs: LogEntry[]; total: number; has_more: boolean }> {
  const params = new URLSearchParams({ limit: limit.toString() })
  if (level) params.set('level', level)
  if (loggerName) params.set('logger_name', loggerName)

  const res = await fetchWithAuth(`${API_BASE}/admin/logs?${params}`)
  return res.json()
}

export async function getSystemInfo(): Promise<{
  version: string
  python_version: string
  data_dir: string
  namespaces: string[]
  environment: Record<string, string>
}> {
  const res = await fetchWithAuth(`${API_BASE}/admin/info`)
  return res.json()
}

export async function getSystemMetrics(): Promise<SystemMetrics> {
  const res = await fetchWithAuth(`${API_BASE}/admin/metrics`)
  return res.json()
}

// Reload
export async function reloadAll(): Promise<{ success: boolean; results: unknown[] }> {
  const res = await fetchWithAuth(`${API_BASE}/reload`, { method: 'POST' })
  return res.json()
}

export async function reloadNamespace(namespace: string): Promise<{ success: boolean; result: unknown }> {
  const res = await fetchWithAuth(`${API_BASE}/reload/${namespace}`, { method: 'POST' })
  return res.json()
}

// Tool Execution (via OpenAPI)
export async function executeTool(
  toolName: string,
  payload: Record<string, unknown>
): Promise<ToolExecutionResult> {
  const res = await fetchWithAuth(`${TOOLS_BASE}/${toolName}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || error.error?.message || 'Tool execution failed')
  }
  return res.json()
}

// Tool info returned by getAllTools
export interface PlaygroundTool {
  name: string
  description: string
  input_schema: Record<string, unknown>
  type: string
  namespace: string
}

// Tool execution response
export interface PlaygroundExecuteResponse {
  tool: string
  transport: string
  result: unknown
  success: boolean
  error?: string
  error_type?: string
  status_code?: number
}

// MCP response format
export interface MCPResponse {
  jsonrpc: string
  id: number
  result?: unknown
  error?: { code: number; message: string }
}

// Get all tools (for playground) - via Backend API for proper logging
export async function getAllTools(): Promise<{
  tools: PlaygroundTool[]
  total: number
}> {
  const res = await fetchWithAuth(`${API_BASE}/playground/tools`)
  return res.json()
}

// Execute tool via playground API (logs locally)
export async function executePlaygroundTool(
  toolName: string,
  payload: Record<string, unknown>,
  transport: 'openapi' | 'mcp' = 'openapi',
  namespace?: string
): Promise<PlaygroundExecuteResponse> {
  const res = await fetchWithAuth(`${API_BASE}/playground/execute`, {
    method: 'POST',
    body: JSON.stringify({
      tool_name: toolName,
      arguments: payload,
      transport,
      namespace,
    }),
  })
  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || 'Tool execution failed')
  }
  return res.json()
}

// Test MCP JSON-RPC format
export async function testMCP(
  method: string,
  params?: Record<string, unknown>
): Promise<MCPResponse> {
  const res = await fetchWithAuth(`${API_BASE}/playground/mcp`, {
    method: 'POST',
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: Date.now(),
      method,
      params,
    }),
  })
  return res.json()
}

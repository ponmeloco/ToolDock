// API Client for OmniMCP Backend

const API_BASE = '/api'
const TOOLS_BASE = '/tools'

// Get auth token from localStorage or prompt
function getAuthToken(): string {
  let token = localStorage.getItem('omnimcp_token')
  if (!token) {
    token = prompt('Enter your Bearer Token:') || ''
    if (token) {
      localStorage.setItem('omnimcp_token', token)
    }
  }
  return token
}

// Clear auth token (for logout)
export function clearAuthToken(): void {
  localStorage.removeItem('omnimcp_token')
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

export interface LogEntry {
  timestamp: string
  level: string
  logger: string
  message: string
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

// Get all tools (for playground)
export async function getAllTools(): Promise<{
  namespace: string
  tools: { name: string; description: string; input_schema: Record<string, unknown> }[]
}> {
  const res = await fetchWithAuth(`${TOOLS_BASE}`)
  return res.json()
}

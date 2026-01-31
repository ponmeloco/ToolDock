import { useState, useRef, useEffect, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import {
  getTools,
  getTool,
  updateTool,
  uploadTool,
  deleteTool,
  validateTool,
  reloadNamespace,
  createToolFromTemplate,
} from '../api/client'
import {
  ArrowLeft,
  File,
  Trash2,
  Save,
  Check,
  X,
  AlertCircle,
  RefreshCw,
  Upload,
  Plus,
} from 'lucide-react'

export default function Tools() {
  const { namespace } = useParams<{ namespace: string }>()
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [editorContent, setEditorContent] = useState('')
  const [originalContent, setOriginalContent] = useState('')
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const [showNewToolModal, setShowNewToolModal] = useState(false)
  const [showUnsavedModal, setShowUnsavedModal] = useState(false)
  const [pendingFileSelect, setPendingFileSelect] = useState<string | null>(null)
  const [newToolName, setNewToolName] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  // Calculate hasChanges from content comparison
  const hasChanges = editorContent !== originalContent && originalContent !== ''

  const toolsQuery = useQuery({
    queryKey: ['tools', namespace],
    queryFn: () => getTools(namespace!),
    enabled: !!namespace,
  })

  const toolContentQuery = useQuery({
    queryKey: ['tool', namespace, selectedFile],
    queryFn: () => getTool(namespace!, selectedFile!),
    enabled: !!namespace && !!selectedFile,
    staleTime: 0, // Always refetch when selected
  })

  // Load editor content when tool data is fetched
  useEffect(() => {
    if (toolContentQuery.data?.content !== undefined) {
      setEditorContent(toolContentQuery.data.content)
      setOriginalContent(toolContentQuery.data.content)
    }
  }, [toolContentQuery.data?.content, selectedFile])

  // Warn before leaving page with unsaved changes
  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasChanges) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', handleBeforeUnload)
    return () => window.removeEventListener('beforeunload', handleBeforeUnload)
  }, [hasChanges])

  const updateMutation = useMutation({
    mutationFn: ({ content }: { content: string }) =>
      updateTool(namespace!, selectedFile!, content),
    onSuccess: (data) => {
      if (data.success) {
        setOriginalContent(editorContent)
        queryClient.invalidateQueries({ queryKey: ['tool', namespace, selectedFile] })
      }
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadTool(namespace!, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools', namespace] })
      queryClient.invalidateQueries({ queryKey: ['namespaces'] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (filename: string) => deleteTool(namespace!, filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools', namespace] })
      queryClient.invalidateQueries({ queryKey: ['namespaces'] })
      if (selectedFile === deleteConfirm) {
        setSelectedFile(null)
        setEditorContent('')
        setOriginalContent('')
      }
      setDeleteConfirm(null)
    },
  })

  const reloadMutation = useMutation({
    mutationFn: () => reloadNamespace(namespace!),
    onSuccess: () => {
      queryClient.invalidateQueries()
    },
  })

  const validateMutation = useMutation({
    mutationFn: () => validateTool(namespace!, editorContent, selectedFile || 'tool.py'),
  })

  const createToolMutation = useMutation({
    mutationFn: (name: string) => createToolFromTemplate(namespace!, name),
    onSuccess: (_, name) => {
      queryClient.invalidateQueries({ queryKey: ['tools', namespace] })
      queryClient.invalidateQueries({ queryKey: ['namespaces'] })
      setShowNewToolModal(false)
      setNewToolName('')
      // Select the new file
      handleSelectFile(`${name}.py`)
    },
  })

  const handleEditorChange = useCallback((value: string) => {
    setEditorContent(value)
  }, [])

  const handleSave = useCallback(() => {
    updateMutation.mutate({ content: editorContent })
  }, [editorContent, updateMutation])

  const handleSelectFile = useCallback((filename: string) => {
    if (filename === selectedFile) return

    if (hasChanges) {
      setPendingFileSelect(filename)
      setShowUnsavedModal(true)
    } else {
      setSelectedFile(filename)
    }
  }, [hasChanges, selectedFile])

  const handleDiscardChanges = useCallback(() => {
    setShowUnsavedModal(false)
    if (pendingFileSelect) {
      setSelectedFile(pendingFileSelect)
      setPendingFileSelect(null)
    }
  }, [pendingFileSelect])

  const handleSaveAndSwitch = useCallback(async () => {
    await updateMutation.mutateAsync({ content: editorContent })
    setShowUnsavedModal(false)
    if (pendingFileSelect) {
      setSelectedFile(pendingFileSelect)
      setPendingFileSelect(null)
    }
  }, [editorContent, pendingFileSelect, updateMutation])

  const handleCancelSwitch = useCallback(() => {
    setShowUnsavedModal(false)
    setPendingFileSelect(null)
  }, [])

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      uploadMutation.mutate(file)
      e.target.value = ''
    }
  }

  const handleCreateTool = () => {
    if (newToolName.trim()) {
      createToolMutation.mutate(newToolName.trim().replace(/\.py$/, ''))
    }
  }

  const handleBackClick = (e: React.MouseEvent) => {
    if (hasChanges) {
      e.preventDefault()
      setPendingFileSelect(null)
      setShowUnsavedModal(true)
    }
  }

  const validation = updateMutation.data?.validation || validateMutation.data || toolContentQuery.data?.validation

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <Link
            to="/namespaces"
            onClick={handleBackClick}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <h1 className="text-2xl font-bold text-gray-900">{namespace}</h1>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => reloadMutation.mutate()}
            disabled={reloadMutation.isPending}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            <RefreshCw className={`w-4 h-4 ${reloadMutation.isPending ? 'animate-spin' : ''}`} />
            Reload
          </button>

          <button
            onClick={() => setShowNewToolModal(true)}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Tool
          </button>

          <input
            ref={fileInputRef}
            type="file"
            accept=".py"
            onChange={handleFileUpload}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadMutation.isPending}
            className="flex items-center gap-2 px-3 py-2 text-sm bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors"
          >
            <Upload className="w-4 h-4" />
            Upload
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* File List */}
        <div className="w-64 bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col">
          <div className="p-3 border-b border-gray-200 font-medium text-gray-900">
            Tools ({toolsQuery.data?.length || 0})
          </div>

          <div className="flex-1 overflow-auto">
            {toolsQuery.isLoading ? (
              <div className="p-3 text-gray-500 text-sm">Loading...</div>
            ) : toolsQuery.data?.length === 0 ? (
              <div className="p-3 text-gray-500 text-sm">No tools yet. Create one!</div>
            ) : (
              <ul className="divide-y divide-gray-100">
                {toolsQuery.data?.map((tool) => (
                  <li key={tool.filename} className="group">
                    <div
                      className={`flex items-center justify-between p-3 cursor-pointer transition-colors ${
                        selectedFile === tool.filename
                          ? 'bg-primary-50 border-l-2 border-primary-600'
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      <button
                        onClick={() => handleSelectFile(tool.filename)}
                        className="flex items-center gap-2 flex-1 text-left"
                      >
                        <File className="w-4 h-4 text-gray-400" />
                        <span className="text-sm truncate">{tool.filename}</span>
                        {selectedFile === tool.filename && hasChanges && (
                          <span className="w-2 h-2 bg-yellow-500 rounded-full" title="Unsaved changes" />
                        )}
                      </button>

                      {deleteConfirm === tool.filename ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => deleteMutation.mutate(tool.filename)}
                            className="p-1 text-red-600 hover:bg-red-100 rounded"
                            title="Confirm delete"
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => setDeleteConfirm(null)}
                            className="p-1 text-gray-600 hover:bg-gray-100 rounded"
                            title="Cancel"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setDeleteConfirm(tool.filename)
                          }}
                          className="p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded opacity-0 group-hover:opacity-100 transition-opacity"
                          title="Delete tool"
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
        </div>

        {/* Editor */}
        <div className="flex-1 bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col min-h-0">
          {selectedFile ? (
            <>
              {/* Editor Header */}
              <div className="flex items-center justify-between p-3 border-b border-gray-200">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-gray-900">{selectedFile}</span>
                  {hasChanges && (
                    <span className="text-xs text-yellow-600 bg-yellow-100 px-2 py-0.5 rounded">
                      Modified
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  {hasChanges && (
                    <button
                      onClick={() => {
                        setEditorContent(originalContent)
                      }}
                      className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded transition-colors"
                    >
                      Discard
                    </button>
                  )}
                  <button
                    onClick={() => validateMutation.mutate()}
                    disabled={validateMutation.isPending}
                    className="px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded transition-colors"
                  >
                    Validate
                  </button>
                  <button
                    onClick={handleSave}
                    disabled={!hasChanges || updateMutation.isPending}
                    className="flex items-center gap-2 px-3 py-1.5 text-sm bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded transition-colors"
                  >
                    <Save className="w-4 h-4" />
                    {updateMutation.isPending ? 'Saving...' : 'Save'}
                  </button>
                </div>
              </div>

              {/* Validation Messages */}
              {validation && (
                <div className={`p-3 border-b text-sm ${
                  validation.is_valid
                    ? 'bg-green-50 border-green-200 text-green-800'
                    : 'bg-red-50 border-red-200 text-red-800'
                }`}>
                  <div className="flex items-center gap-2">
                    {validation.is_valid ? (
                      <Check className="w-4 h-4" />
                    ) : (
                      <AlertCircle className="w-4 h-4" />
                    )}
                    <span className="font-medium">
                      {validation.is_valid ? 'Valid' : 'Validation Errors'}
                    </span>
                  </div>
                  {validation.errors && validation.errors.length > 0 && (
                    <ul className="mt-1 ml-6 list-disc">
                      {validation.errors.map((err: string, i: number) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  )}
                  {validation.warnings && validation.warnings.length > 0 && (
                    <ul className="mt-1 ml-6 list-disc text-yellow-700">
                      {validation.warnings.map((warn: string, i: number) => (
                        <li key={i}>{warn}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {/* Editor */}
              <div className="flex-1 overflow-auto">
                {toolContentQuery.isLoading ? (
                  <div className="p-4 text-gray-500">Loading...</div>
                ) : toolContentQuery.isError ? (
                  <div className="p-4 text-red-500">Failed to load tool content</div>
                ) : (
                  <CodeMirror
                    value={editorContent}
                    onChange={handleEditorChange}
                    extensions={[python()]}
                    theme="light"
                    className="h-full text-sm"
                    basicSetup={{
                      lineNumbers: true,
                      highlightActiveLineGutter: true,
                      highlightActiveLine: true,
                      foldGutter: true,
                    }}
                  />
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-500">
              Select a tool to edit or create a new one
            </div>
          )}
        </div>
      </div>

      {/* Unsaved Changes Modal */}
      {showUnsavedModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-lg p-6 w-full max-w-md">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">Unsaved Changes</h2>
            <p className="text-gray-600 mb-4">
              You have unsaved changes in <strong>{selectedFile}</strong>. What would you like to do?
            </p>

            <div className="flex justify-end gap-2">
              <button
                onClick={handleCancelSwitch}
                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDiscardChanges}
                className="px-4 py-2 text-sm text-red-600 hover:bg-red-50 rounded-lg transition-colors"
              >
                Discard
              </button>
              <button
                onClick={handleSaveAndSwitch}
                disabled={updateMutation.isPending}
                className="px-4 py-2 text-sm bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded-lg transition-colors"
              >
                {updateMutation.isPending ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* New Tool Modal */}
      {showNewToolModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-lg p-6 w-full max-w-md">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Create New Tool</h2>

            <div className="mb-4">
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Tool Name
              </label>
              <input
                type="text"
                value={newToolName}
                onChange={(e) => setNewToolName(e.target.value)}
                placeholder="my_tool"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleCreateTool()
                  if (e.key === 'Escape') setShowNewToolModal(false)
                }}
              />
              <p className="mt-1 text-xs text-gray-500">
                Use snake_case (e.g., my_tool, fetch_data)
              </p>
            </div>

            <div className="flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowNewToolModal(false)
                  setNewToolName('')
                }}
                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateTool}
                disabled={!newToolName.trim() || createToolMutation.isPending}
                className="px-4 py-2 text-sm bg-primary-600 hover:bg-primary-700 disabled:opacity-50 text-white rounded-lg transition-colors"
              >
                {createToolMutation.isPending ? 'Creating...' : 'Create'}
              </button>
            </div>

            {createToolMutation.isError && (
              <p className="mt-3 text-sm text-red-600">
                Failed to create tool. Please try again.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

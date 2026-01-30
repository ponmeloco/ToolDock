import { useState, useRef } from 'react'
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
} from 'lucide-react'

export default function Tools() {
  const { namespace } = useParams<{ namespace: string }>()
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [editorContent, setEditorContent] = useState('')
  const [hasChanges, setHasChanges] = useState(false)
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const toolsQuery = useQuery({
    queryKey: ['tools', namespace],
    queryFn: () => getTools(namespace!),
    enabled: !!namespace,
  })

  const toolContentQuery = useQuery({
    queryKey: ['tool', namespace, selectedFile],
    queryFn: () => getTool(namespace!, selectedFile!),
    enabled: !!namespace && !!selectedFile,
  })

  const updateMutation = useMutation({
    mutationFn: ({ content }: { content: string }) =>
      updateTool(namespace!, selectedFile!, content),
    onSuccess: (data) => {
      if (data.success) {
        queryClient.invalidateQueries({ queryKey: ['tool', namespace, selectedFile] })
        setHasChanges(false)
      }
    },
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadTool(namespace!, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools', namespace] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (filename: string) => deleteTool(namespace!, filename),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tools', namespace] })
      if (selectedFile === deleteConfirm) {
        setSelectedFile(null)
        setEditorContent('')
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

  // When tool content loads, set editor content
  if (toolContentQuery.data && editorContent !== toolContentQuery.data.content && !hasChanges) {
    setEditorContent(toolContentQuery.data.content)
  }

  const handleEditorChange = (value: string) => {
    setEditorContent(value)
    setHasChanges(value !== toolContentQuery.data?.content)
  }

  const handleSave = () => {
    updateMutation.mutate({ content: editorContent })
  }

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      uploadMutation.mutate(file)
      e.target.value = ''
    }
  }

  const validation = updateMutation.data?.validation || toolContentQuery.data?.validation

  return (
    <div className="h-[calc(100vh-3rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <Link
            to="/namespaces"
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
            Upload Tool
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* File List */}
        <div className="w-64 bg-white rounded-xl shadow-sm border border-gray-200 flex flex-col">
          <div className="p-3 border-b border-gray-200 font-medium text-gray-900">
            Tools
          </div>

          <div className="flex-1 overflow-auto">
            {toolsQuery.isLoading ? (
              <div className="p-3 text-gray-500 text-sm">Loading...</div>
            ) : toolsQuery.data?.length === 0 ? (
              <div className="p-3 text-gray-500 text-sm">No tools yet</div>
            ) : (
              <ul className="divide-y divide-gray-100">
                {toolsQuery.data?.map((tool) => (
                  <li key={tool.filename}>
                    <div
                      className={`flex items-center justify-between p-3 cursor-pointer transition-colors ${
                        selectedFile === tool.filename
                          ? 'bg-primary-50 border-l-2 border-primary-600'
                          : 'hover:bg-gray-50'
                      }`}
                    >
                      <button
                        onClick={() => {
                          if (hasChanges && !confirm('Discard changes?')) return
                          setSelectedFile(tool.filename)
                          setHasChanges(false)
                        }}
                        className="flex items-center gap-2 flex-1 text-left"
                      >
                        <File className="w-4 h-4 text-gray-400" />
                        <span className="text-sm truncate">{tool.filename}</span>
                      </button>

                      {deleteConfirm === tool.filename ? (
                        <div className="flex items-center gap-1">
                          <button
                            onClick={() => deleteMutation.mutate(tool.filename)}
                            className="p-1 text-red-600 hover:bg-red-100 rounded"
                          >
                            <Check className="w-3 h-3" />
                          </button>
                          <button
                            onClick={() => setDeleteConfirm(null)}
                            className="p-1 text-gray-600 hover:bg-gray-100 rounded"
                          >
                            <X className="w-3 h-3" />
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setDeleteConfirm(tool.filename)}
                          className="p-1 text-gray-400 hover:text-red-600 opacity-0 group-hover:opacity-100"
                        >
                          <Trash2 className="w-3 h-3" />
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
                    Save
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
                  {validation.errors.length > 0 && (
                    <ul className="mt-1 ml-6 list-disc">
                      {validation.errors.map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  )}
                  {validation.warnings.length > 0 && (
                    <ul className="mt-1 ml-6 list-disc text-yellow-700">
                      {validation.warnings.map((warn, i) => (
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
                ) : (
                  <CodeMirror
                    value={editorContent}
                    onChange={handleEditorChange}
                    extensions={[python()]}
                    theme="light"
                    className="h-full"
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
              Select a tool to edit or upload a new one
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

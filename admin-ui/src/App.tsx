import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Namespaces from './pages/Namespaces'
import Tools from './pages/Tools'
import Playground from './pages/Playground'
import Logs from './pages/Logs'
import Docs from './pages/Docs'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="namespaces" element={<Namespaces />} />
        <Route path="namespaces/:namespace" element={<Tools />} />
        <Route path="playground" element={<Playground />} />
        <Route path="logs" element={<Logs />} />
        <Route path="docs" element={<Docs />} />
      </Route>
    </Routes>
  )
}

export default App

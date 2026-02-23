import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Login } from '@/pages/Login'
import { Dashboard } from '@/pages/Dashboard'
import { Research } from '@/pages/Research'

export function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-[var(--muted-foreground)]">Loading...</div>
      </div>
    )
  }

  if (!user) {
    return <Login />
  }

  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/research/:ticker" element={<Research />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App

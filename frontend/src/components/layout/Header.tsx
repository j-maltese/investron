import { Link } from 'react-router-dom'
import { Moon, Sun, LogOut, TrendingUp } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useAuth } from '@/hooks/useAuth'
import { CompanySearch } from '@/components/search/CompanySearch'

export function Header() {
  const { theme, toggleTheme } = useTheme()
  const { user, signOut } = useAuth()

  return (
    <header className="border-b border-[var(--border)] bg-[var(--card)]">
      <div className="px-8 h-14 flex items-center justify-between gap-4">
        <Link to="/" className="flex items-center gap-2 font-bold text-lg shrink-0">
          <TrendingUp className="w-5 h-5 text-[var(--accent)]" />
          Investron
        </Link>

        <div className="flex-1 max-w-md">
          <CompanySearch />
        </div>

        <nav className="flex items-center gap-2">
          <Link to="/" className="px-3 py-1.5 rounded-md text-sm hover:bg-[var(--muted)] transition-colors">
            Dashboard
          </Link>
          <Link to="/docs" className="px-3 py-1.5 rounded-md text-sm hover:bg-[var(--muted)] transition-colors">
            Docs
          </Link>

          <button
            onClick={toggleTheme}
            className="p-2 rounded-md hover:bg-[var(--muted)] transition-colors"
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>

          {user && (
            <button
              onClick={signOut}
              className="p-2 rounded-md hover:bg-[var(--muted)] transition-colors"
              title="Sign out"
            >
              <LogOut className="w-4 h-4" />
            </button>
          )}
        </nav>
      </div>
    </header>
  )
}

import type { ReactNode } from 'react'
import { Header } from './Header'

interface PageLayoutProps {
  children: ReactNode
}

export function PageLayout({ children }: PageLayoutProps) {
  return (
    <div className="min-h-screen flex flex-col">
      <Header />
      <main className="flex-1 max-w-7xl mx-auto w-full px-4 py-6">
        {children}
      </main>
    </div>
  )
}

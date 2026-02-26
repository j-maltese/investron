import { useState, useEffect } from 'react'
import type { Session, User } from '@supabase/supabase-js'
import { supabase, isDevMode } from '@/lib/supabase'

// Fake user for local dev — mirrors Supabase shape just enough for the app
const DEV_USER = {
  id: 'dev-user-001',
  email: 'dev@investron.local',
  app_metadata: {},
  user_metadata: { full_name: 'Dev User' },
  aud: 'authenticated',
  created_at: new Date().toISOString(),
} as unknown as User

export function useAuth() {
  const [session, setSession] = useState<Session | null>(null)
  const [user, setUser] = useState<User | null>(isDevMode ? DEV_USER : null)
  const [loading, setLoading] = useState(!isDevMode)

  useEffect(() => {
    // In dev mode without Supabase, we already have a fake user — skip auth
    if (isDevMode || !supabase) return

    supabase.auth.getSession().then(({ data: { session } }) => {
      setSession(session)
      setUser(session?.user ?? null)
      setLoading(false)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setSession(session)
        setUser(session?.user ?? null)
        setLoading(false)
      }
    )

    return () => subscription.unsubscribe()
  }, [])

  const signInWithGoogle = async () => {
    if (!supabase) return
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin,
      },
    })
    if (error) throw error
  }

  const signOut = async () => {
    if (!supabase) return
    const { error } = await supabase.auth.signOut()
    if (error) throw error
  }

  return { session, user, loading, signInWithGoogle, signOut }
}

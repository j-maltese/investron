import { createClient, SupabaseClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || ''
const supabaseKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY || ''

// When Supabase is not configured (local dev with backend DEBUG=true),
// export null instead of a broken client. Consumers check this before
// calling supabase.auth.* methods.
export const supabase: SupabaseClient | null =
  supabaseUrl && supabaseKey
    ? createClient(supabaseUrl, supabaseKey)
    : null

// True when running without Supabase (local dev mode)
export const isDevMode = supabase === null

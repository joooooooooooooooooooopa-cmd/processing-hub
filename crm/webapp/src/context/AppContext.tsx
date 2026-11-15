import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react'

interface AppState {
  favorites: string[]
  toggleFavorite: (name: string) => void
  isFavorite: (name: string) => boolean
}

const AppContext = createContext<AppState | null>(null)

export function useApp(): AppState {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [favorites, setFavorites] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('crm_favorite_merchants') || '[]')
    } catch {
      return []
    }
  })

  useEffect(() => {
    localStorage.setItem('crm_favorite_merchants', JSON.stringify(favorites))
  }, [favorites])

  const toggleFavorite = useCallback((name: string) => {
    setFavorites(prev =>
      prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]
    )
  }, [])

  const isFavorite = useCallback((name: string) => favorites.includes(name), [favorites])

  return (
    <AppContext.Provider value={{ favorites, toggleFavorite, isFavorite }}>
      {children}
    </AppContext.Provider>
  )
}

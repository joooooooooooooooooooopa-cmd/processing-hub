import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AppProvider } from './context/AppContext'

const tg = (window as any).Telegram?.WebApp
if (tg) {
  tg.ready()
  tg.expand()
}

createRoot(document.getElementById('root')!).render(
  <AppProvider>
    <App />
  </AppProvider>
)

import { useState } from 'react'

interface Props {
  onLogin: (userId: number, accessKey: string) => void
}

export default function StandaloneLogin({ onLogin }: Props) {
  const [userId, setUserId] = useState('')
  const [accessKey, setAccessKey] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    const uid = parseInt(userId, 10)
    if (isNaN(uid) || uid <= 0) {
      setError('Неверный Telegram User ID')
      return
    }

    if (!accessKey.trim()) {
      setError('Введите ключ доступа')
      return
    }

    onLogin(uid, accessKey)
  }

  return (
    <div
      className="flex items-center justify-center min-h-screen p-4"
      style={{ background: '#050505' }}
    >
      <div className="w-full max-w-md">
        <div
          className="rounded-2xl p-8 backdrop-blur-sm"
          style={{
            background: 'rgba(13,17,23,0.8)',
            border: '1px solid rgba(16,185,129,0.1)',
            boxShadow: '0 0 30px rgba(16,185,129,0.08)',
          }}
        >
          <div className="text-center mb-8">
            <h1 className="text-2xl font-bold" style={{ color: '#f0fdf4' }}>
              ProcessingHub
            </h1>
            <p className="text-sm mt-2" style={{ color: '#9ca3af' }}>
              Войдите для доступа к системе
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label
                htmlFor="userId"
                className="block text-sm font-medium mb-2"
                style={{ color: '#9ca3af' }}
              >
                Telegram User ID
              </label>
              <input
                id="userId"
                type="number"
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                className="w-full px-4 py-3 rounded-xl text-sm transition-all duration-200 outline-none"
                style={{
                  background: 'rgba(255,255,255,0.05)',
                  border: '1px solid rgba(107,114,128,0.3)',
                  color: '#f0fdf4',
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(16,185,129,0.5)'
                  e.currentTarget.style.boxShadow = '0 0 0 3px rgba(16,185,129,0.1)'
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(107,114,128,0.3)'
                  e.currentTarget.style.boxShadow = 'none'
                }}
                placeholder="123456789"
                required
              />
            </div>

            <div>
              <label
                htmlFor="accessKey"
                className="block text-sm font-medium mb-2"
                style={{ color: '#9ca3af' }}
              >
                Ключ доступа
              </label>
              <input
                id="accessKey"
                type="password"
                value={accessKey}
                onChange={(e) => setAccessKey(e.target.value)}
                className="w-full px-4 py-3 rounded-xl text-sm transition-all duration-200 outline-none"
                style={{
                  background: 'rgba(255,255,255,0.05)',
                  border: '1px solid rgba(107,114,128,0.3)',
                  color: '#f0fdf4',
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(16,185,129,0.5)'
                  e.currentTarget.style.boxShadow = '0 0 0 3px rgba(16,185,129,0.1)'
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = 'rgba(107,114,128,0.3)'
                  e.currentTarget.style.boxShadow = 'none'
                }}
                placeholder="Введите ключ"
                required
              />
            </div>

            {error && (
              <div
                className="text-sm rounded-xl p-3"
                style={{
                  color: '#fca5a5',
                  background: 'rgba(239,68,68,0.1)',
                  border: '1px solid rgba(239,68,68,0.2)',
                }}
              >
                {error}
              </div>
            )}

            <button
              type="submit"
              className="w-full font-medium py-3 px-4 rounded-xl transition-all duration-200"
              style={{
                background: 'linear-gradient(135deg, #10b981, #059669)',
                color: '#f0fdf4',
                boxShadow: '0 0 15px rgba(16,185,129,0.25)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow = '0 0 25px rgba(16,185,129,0.4)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = '0 0 15px rgba(16,185,129,0.25)'
              }}
            >
              Войти
            </button>
          </form>

          <div className="mt-6 text-xs text-center" style={{ color: '#6b7280' }}>
            <p>Получите ключ доступа у администратора</p>
            <p className="mt-1">Ваш Telegram ID можно узнать у @userinfobot</p>
          </div>
        </div>
      </div>
    </div>
  )
}

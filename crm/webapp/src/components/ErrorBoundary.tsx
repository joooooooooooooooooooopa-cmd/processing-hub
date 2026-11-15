import { Component, type ReactNode } from 'react'

interface Props { children: ReactNode }
interface State { error: string | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(e: Error): State {
    return { error: e.message || 'Ошибка рендеринга' }
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            padding: 16,
            margin: 8,
            fontSize: 13,
            color: '#fca5a5',
            background: 'rgba(239,68,68,0.1)',
            border: '1px solid rgba(239,68,68,0.2)',
            borderRadius: 12,
          }}
        >
          <span style={{ marginRight: 6 }}>&#x26A0;</span>
          {this.state.error}
        </div>
      )
    }
    return this.props.children
  }
}

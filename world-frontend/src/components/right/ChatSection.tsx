import { useState, useRef, useEffect } from 'react'
import { useWorldContext } from '../../context/WorldContext'
import { useChat } from '../../hooks/useChat'
import FormattedText from './FormattedText'

export default function ChatSection({ expanded, onToggle }: { expanded: boolean; onToggle: () => void }) {
  const { activeChapterId } = useWorldContext()
  const { messages, loading, sendMessage } = useChat(activeChapterId)
  const [input, setInput] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (expanded) endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, expanded])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || loading) return
    const q = input.trim()
    setInput('')
    await sendMessage(q)
  }

  if (!expanded) {
    return (
      <form onSubmit={handleSubmit} style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        padding: '8px 12px',
        height: '48px',
      }}>
        <button
          type="button"
          onClick={onToggle}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            fontSize: '14px',
            color: 'var(--text-muted)',
            padding: '2px 4px',
          }}
          title="Expand chat"
        >
          ▲
        </button>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask about this period..."
          style={{
            flex: 1,
            padding: '7px 10px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
            background: 'var(--bg-tertiary)',
            color: 'var(--text-primary)',
            fontSize: '11px',
            outline: 'none',
          }}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          style={{
            padding: '7px 12px',
            borderRadius: '6px',
            border: 'none',
            background: loading || !input.trim() ? 'var(--bg-tertiary)' : 'var(--accent)',
            color: loading || !input.trim() ? 'var(--text-muted)' : '#fff',
            fontSize: '11px',
            fontWeight: 600,
            cursor: loading || !input.trim() ? 'default' : 'pointer',
          }}
        >
          Send
        </button>
      </form>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{
        padding: '8px 12px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexShrink: 0,
      }}>
        <span style={{ fontSize: '10px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Research Chat
        </span>
        <button
          onClick={onToggle}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            fontSize: '12px',
            color: 'var(--text-muted)',
            padding: '2px 4px',
          }}
        >
          ▼
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px 10px' }}>
        {messages.length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: '16px 8px',
            color: 'var(--text-muted)',
            fontSize: '11px',
          }}>
            Ask about history, actors, events, or artifacts. Answers are grounded in source evidence only.
          </div>
        )}

        {messages.map(msg => (
          <div key={msg.id} style={{ marginBottom: '8px' }}>
            <div style={{
              display: 'flex',
              justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start',
            }}>
              <div style={{
                maxWidth: '88%',
                padding: '8px 10px',
                borderRadius: msg.role === 'user' ? '10px 10px 2px 10px' : '10px 10px 10px 2px',
                background: msg.role === 'user' ? 'var(--accent)' : 'var(--bg-tertiary)',
                color: msg.role === 'user' ? '#fff' : 'var(--text-primary)',
                fontSize: '11px',
                lineHeight: 1.5,
              }}>
                {msg.role === 'assistant' ? <FormattedText text={msg.content} /> : msg.content}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '8px' }}>
            <div style={{
              padding: '8px 10px',
              borderRadius: '10px 10px 10px 2px',
              background: 'var(--bg-tertiary)',
              color: 'var(--text-muted)',
              fontSize: '11px',
              animation: 'pulse 1s infinite',
            }}>
              Thinking...
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={handleSubmit} style={{
        padding: '8px 10px',
        borderTop: '1px solid var(--border)',
        display: 'flex',
        gap: '6px',
        flexShrink: 0,
      }}>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Ask a question..."
          disabled={loading}
          style={{
            flex: 1,
            padding: '7px 10px',
            borderRadius: '6px',
            border: '1px solid var(--border)',
            background: 'var(--bg-tertiary)',
            color: 'var(--text-primary)',
            fontSize: '11px',
            outline: 'none',
          }}
          onFocus={e => (e.target.style.borderColor = 'var(--accent)')}
          onBlur={e => (e.target.style.borderColor = 'var(--border)')}
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          style={{
            padding: '7px 12px',
            borderRadius: '6px',
            border: 'none',
            background: loading || !input.trim() ? 'var(--bg-tertiary)' : 'var(--accent)',
            color: loading || !input.trim() ? 'var(--text-muted)' : '#fff',
            fontSize: '11px',
            fontWeight: 600,
            cursor: loading || !input.trim() ? 'default' : 'pointer',
          }}
        >
          Send
        </button>
      </form>
    </div>
  )
}

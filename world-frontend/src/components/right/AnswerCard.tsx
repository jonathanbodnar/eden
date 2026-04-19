import type { ChatQueryResult, AnswerSource, AnswerContext } from '../../api'

function modeLabel(mode: string): { text: string; color: string } {
  switch (mode) {
    case 'source': return { text: 'Source-backed', color: 'var(--success)' }
    case 'context': return { text: 'Context-based', color: 'var(--accent)' }
    case 'synthesis': return { text: 'Synthesized', color: 'var(--warning)' }
    default: return { text: 'Unsupported', color: 'var(--error)' }
  }
}

function formatCategory(cat: string | null): string {
  if (!cat) return ''
  return cat.replace(/_/g, ' ')
}

export default function AnswerCard({
  answer, sources, contexts,
}: {
  answer: ChatQueryResult
  sources: AnswerSource[]
  contexts: AnswerContext[]
}) {
  const mode = modeLabel(answer.answer_mode)
  const hasCitations = sources.length > 0 || contexts.length > 0

  if (!hasCitations) {
    return (
      <div style={{
        marginTop: '6px',
        marginLeft: '4px',
        display: 'flex',
        gap: '8px',
        alignItems: 'center',
        fontSize: '10px',
      }}>
        <span style={{ color: mode.color, fontWeight: 600 }}>{mode.text}</span>
        <span style={{ color: 'var(--text-muted)' }}>
          {(answer.confidence * 100).toFixed(0)}% confidence
        </span>
      </div>
    )
  }

  return (
    <div style={{
      marginTop: '8px',
      marginLeft: '4px',
      background: 'var(--bg-primary)',
      border: '1px solid var(--border)',
      borderRadius: '6px',
      padding: '10px 12px',
      fontSize: '11px',
    }}>
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '8px',
      }}>
        <span style={{ color: mode.color, fontWeight: 600 }}>
          {mode.text}
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          {(answer.confidence * 100).toFixed(0)}% confidence
        </span>
      </div>

      {sources.length > 0 && (
        <div style={{ marginBottom: contexts.length > 0 ? '8px' : '0' }}>
          <div style={{
            fontSize: '10px',
            color: 'var(--text-muted)',
            fontWeight: 600,
            marginBottom: '4px',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}>
            Sources ({sources.length})
          </div>
          {sources.map(src => (
            <div key={src.id} style={{
              padding: '6px 8px',
              background: 'var(--bg-secondary)',
              borderRadius: '4px',
              marginBottom: '3px',
              borderLeft: '2px solid var(--accent)',
            }}>
              {src.excerpt ? (
                <div style={{
                  color: 'var(--text-secondary)',
                  lineHeight: 1.4,
                }}>
                  {src.excerpt.slice(0, 150)}
                  {src.excerpt.length > 150 && '...'}
                </div>
              ) : (
                <div style={{ color: 'var(--text-secondary)' }}>
                  Source record
                </div>
              )}
              {src.support_type && (
                <div style={{
                  marginTop: '3px',
                  color: 'var(--text-muted)',
                  fontSize: '10px',
                }}>
                  {formatCategory(src.support_type)}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {contexts.length > 0 && (
        <div>
          <div style={{
            fontSize: '10px',
            color: 'var(--text-muted)',
            fontWeight: 600,
            marginBottom: '4px',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}>
            Text Evidence ({contexts.length})
          </div>
          {contexts.map(ctx => (
            <div key={ctx.id} style={{
              padding: '6px 8px',
              background: 'var(--bg-secondary)',
              borderRadius: '4px',
              marginBottom: '3px',
              borderLeft: '2px solid var(--warning)',
            }}>
              <div style={{
                color: 'var(--text-secondary)',
                lineHeight: 1.4,
                fontStyle: 'italic',
              }}>
                {ctx.summary
                  ? ctx.summary.slice(0, 200) + (ctx.summary.length > 200 ? '...' : '')
                  : 'Context reference'}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

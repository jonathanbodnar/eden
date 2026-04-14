import type { StoryChapter, StoryEvidence } from '../../api'

interface Props {
  chapter: StoryChapter | null
  evidence: StoryEvidence[]
}

function formatDate(y: number | null): string {
  if (y === null) return ''
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

export default function EvidencePanel({ chapter, evidence }: Props) {
  if (!chapter) {
    return (
      <div style={{
        background: 'var(--bg-secondary)',
        borderLeft: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--text-muted)',
        fontSize: 13,
        padding: 20,
      }}>
        Select a chapter to see evidence
      </div>
    )
  }

  const cultureCounts: Record<string, number> = {}
  for (const claim of chapter.claims || []) {
    for (const c of claim.cultures || []) {
      cultureCounts[c] = (cultureCounts[c] || 0) + 1
    }
  }
  const cultureList = Object.entries(cultureCounts)
    .sort((a, b) => b[1] - a[1])

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      borderLeft: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '16px',
        borderBottom: '1px solid var(--border)',
      }}>
        <div style={{
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: 1.5,
          color: 'var(--gold)',
          marginBottom: 4,
        }}>
          Evidence
        </div>
        <div style={{
          fontSize: 14,
          fontWeight: 600,
          color: 'var(--text-primary)',
          lineHeight: 1.3,
        }}>
          {chapter.chapter_title}
        </div>
        {(chapter.time_start !== null || chapter.time_end !== null) && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            {formatDate(chapter.time_start)}{chapter.time_end ? ` — ${formatDate(chapter.time_end)}` : ''}
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        {/* Culture Distribution */}
        {cultureList.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 1,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}>
              Cultural Distribution
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {cultureList.map(([culture, count]) => (
                <span
                  key={culture}
                  style={{
                    padding: '3px 10px',
                    background: count >= 3 ? 'rgba(212, 168, 83, 0.15)' : 'var(--bg-tertiary)',
                    border: `1px solid ${count >= 3 ? 'var(--gold)' : 'var(--border)'}`,
                    borderRadius: 12,
                    fontSize: 11,
                    color: count >= 3 ? 'var(--gold)' : 'var(--text-secondary)',
                    fontWeight: 500,
                  }}
                >
                  {culture} ({count})
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Score Breakdown */}
        {chapter.claims && chapter.claims.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 1,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}>
              Claim Confidence
            </div>
            {chapter.claims.slice(0, 8).map((claim, i) => (
              <div key={i} style={{
                marginBottom: 8,
                padding: '8px 10px',
                background: 'var(--bg-tertiary)',
                borderRadius: 6,
              }}>
                <div style={{ fontSize: 12, color: 'var(--text-primary)', marginBottom: 4, lineHeight: 1.4 }}>
                  {claim.claim}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    flex: 1,
                    height: 4,
                    background: 'var(--bg-secondary)',
                    borderRadius: 2,
                    overflow: 'hidden',
                  }}>
                    <div style={{
                      height: '100%',
                      width: `${(claim.score || 0) * 100}%`,
                      background: (claim.score || 0) >= 0.7 ? 'var(--gold)' : (claim.score || 0) >= 0.4 ? 'var(--accent)' : 'var(--text-muted)',
                      borderRadius: 2,
                    }} />
                  </div>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', minWidth: 28 }}>
                    {((claim.score || 0) * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Source Excerpts */}
        {evidence.length > 0 && (
          <div>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 1,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}>
              Source Texts ({evidence.length})
            </div>
            {evidence.map((ev, i) => (
              <details
                key={ev.source_id || i}
                style={{
                  marginBottom: 6,
                  background: 'var(--bg-tertiary)',
                  borderRadius: 6,
                  overflow: 'hidden',
                }}
              >
                <summary style={{
                  padding: '8px 10px',
                  cursor: 'pointer',
                  fontSize: 12,
                  color: 'var(--text-primary)',
                  fontWeight: 500,
                  listStyle: 'none',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}>
                  <span style={{ flex: 1, marginRight: 8 }}>{ev.title}</span>
                  {ev.culture && (
                    <span style={{
                      fontSize: 10,
                      padding: '2px 6px',
                      background: 'var(--bg-secondary)',
                      borderRadius: 8,
                      color: 'var(--text-muted)',
                      flexShrink: 0,
                    }}>
                      {ev.culture}
                    </span>
                  )}
                </summary>
                <div style={{
                  padding: '0 10px 10px',
                  fontSize: 12,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.6,
                  fontFamily: "'Georgia', 'Times New Roman', serif",
                  fontStyle: 'italic',
                }}>
                  {ev.excerpt || 'No excerpt available'}
                  {ev.origin_place && (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, fontStyle: 'normal' }}>
                      Origin: {ev.origin_place}
                    </div>
                  )}
                </div>
              </details>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

import { useRef, useEffect, useCallback } from 'react'
import type { StoryChapter } from '../../api'

interface Props {
  chapters: StoryChapter[]
  activeChapterId: string | null
  onChapterInView: (id: string) => void
}

function formatDate(y: number | null): string {
  if (y === null) return ''
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

function ClaimIndicator({ cultures, score }: { cultures: string[]; score: number }) {
  const isStrong = cultures.length >= 3 || score >= 0.7
  return (
    <span
      title={`${cultures.length} culture${cultures.length !== 1 ? 's' : ''}: ${cultures.join(', ')} (score: ${score.toFixed(2)})`}
      style={{
        display: 'inline-block',
        width: 3,
        height: '100%',
        minHeight: 16,
        background: isStrong ? 'var(--gold)' : 'var(--border)',
        borderRadius: 1,
        marginRight: 8,
        flexShrink: 0,
      }}
    />
  )
}

export default function NarrativeReader({ chapters, activeChapterId, onChapterInView }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const chapterRefs = useRef<Map<string, HTMLDivElement>>(new Map())
  const userScrolling = useRef(false)

  useEffect(() => {
    if (!activeChapterId || userScrolling.current) return
    const el = chapterRefs.current.get(activeChapterId)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [activeChapterId])

  const handleScroll = useCallback(() => {
    if (!scrollRef.current) return
    userScrolling.current = true

    const container = scrollRef.current
    const scrollTop = container.scrollTop
    const containerHeight = container.clientHeight

    let closestId: string | null = null
    let closestDist = Infinity

    chapterRefs.current.forEach((el, id) => {
      const rect = el.getBoundingClientRect()
      const containerRect = container.getBoundingClientRect()
      const relativeTop = rect.top - containerRect.top
      const dist = Math.abs(relativeTop - containerHeight * 0.2)
      if (dist < closestDist) {
        closestDist = dist
        closestId = id
      }
    })

    if (closestId && closestId !== activeChapterId) {
      onChapterInView(closestId)
    }

    setTimeout(() => { userScrolling.current = false }, 500)
  }, [activeChapterId, onChapterInView])

  return (
    <div
      ref={scrollRef}
      onScroll={handleScroll}
      style={{
        height: '100%',
        overflow: 'auto',
        background: 'var(--bg-primary)',
      }}
    >
      <div style={{ maxWidth: 720, margin: '0 auto', padding: '40px 24px 120px' }}>
        {chapters.map((ch, idx) => {
          const prevEpoch = idx > 0 ? chapters[idx - 1].epoch_id : null
          const showEpochHeader = ch.epoch_id !== prevEpoch

          return (
            <div
              key={ch.id}
              ref={el => { if (el) chapterRefs.current.set(ch.id, el) }}
              style={{ marginBottom: 64 }}
            >
              {showEpochHeader && (
                <div style={{
                  textAlign: 'center',
                  padding: '40px 0 32px',
                  borderTop: idx > 0 ? '1px solid var(--border)' : 'none',
                  marginTop: idx > 0 ? 40 : 0,
                }}>
                  <div style={{
                    fontSize: 11,
                    textTransform: 'uppercase',
                    letterSpacing: 3,
                    color: 'var(--gold)',
                    marginBottom: 8,
                  }}>
                    Part {chapters.filter((c, i) => i <= idx && c.epoch_id !== (i > 0 ? chapters[i - 1].epoch_id : null)).length}
                  </div>
                  <h1 style={{
                    fontSize: 28,
                    fontWeight: 700,
                    color: 'var(--text-primary)',
                    fontFamily: "'Georgia', 'Times New Roman', serif",
                    lineHeight: 1.3,
                  }}>
                    {ch.epoch_title}
                  </h1>
                </div>
              )}

              <div style={{ marginBottom: 24 }}>
                <h2 style={{
                  fontSize: 20,
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  fontFamily: "'Georgia', 'Times New Roman', serif",
                  marginBottom: 4,
                }}>
                  {ch.chapter_title}
                </h2>
                {(ch.time_start !== null || ch.time_end !== null) && (
                  <div style={{ fontSize: 13, color: 'var(--gold)', fontWeight: 500 }}>
                    {formatDate(ch.time_start)}{ch.time_end !== null && ch.time_start !== ch.time_end ? ` — ${formatDate(ch.time_end)}` : ''}
                  </div>
                )}
              </div>

              {ch.images && ch.images.length > 0 && ch.images[0].url && (
                <div style={{
                  marginBottom: 28,
                  borderRadius: 8,
                  overflow: 'hidden',
                  aspectRatio: '16 / 9',
                  background: 'var(--bg-tertiary)',
                }}>
                  <img
                    src={ch.images[0].url}
                    alt={ch.images[0].caption || ch.chapter_title}
                    style={{
                      width: '100%',
                      height: '100%',
                      objectFit: 'cover',
                    }}
                  />
                </div>
              )}

              <div style={{
                fontSize: 16,
                lineHeight: 1.8,
                color: 'var(--text-primary)',
                fontFamily: "'Georgia', 'Times New Roman', serif",
              }}>
                {ch.narrative_text.split('\n\n').map((para, pIdx) => (
                  <p key={pIdx} style={{ marginBottom: 20, textIndent: pIdx > 0 ? 24 : 0 }}>
                    {para}
                  </p>
                ))}
              </div>

              {ch.claims && ch.claims.length > 0 && (
                <div style={{
                  marginTop: 20,
                  padding: '12px 16px',
                  background: 'var(--bg-secondary)',
                  borderRadius: 8,
                  borderLeft: '3px solid var(--gold)',
                }}>
                  <div style={{
                    fontSize: 11,
                    textTransform: 'uppercase',
                    letterSpacing: 1,
                    color: 'var(--text-muted)',
                    marginBottom: 8,
                  }}>
                    Key Claims
                  </div>
                  {ch.claims.slice(0, 5).map((claim, cIdx) => (
                    <div key={cIdx} style={{
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: 0,
                      marginBottom: 6,
                    }}>
                      <ClaimIndicator cultures={claim.cultures || []} score={claim.score || 0} />
                      <div>
                        <span style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                          {claim.claim}
                        </span>
                        {claim.cultures && claim.cultures.length > 0 && (
                          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6 }}>
                            ({claim.cultures.join(', ')})
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

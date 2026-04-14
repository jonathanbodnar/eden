import { useRef, useEffect, useCallback, useMemo } from 'react'
import type { StoryChapter, EntityMention } from '../../api'

interface Props {
  chapters: StoryChapter[]
  activeChapterId: string | null
  onChapterInView: (id: string) => void
  onEntityClick?: (entityType: string, entityId: string, entityName: string) => void
}

const ENTITY_COLORS: Record<string, string> = {
  actor: 'var(--gold)',
  event: '#7eb8da',
  place: '#a8d5a2',
}

function parseNarrativeWithEntities(
  text: string,
  mentions: EntityMention[],
  onEntityClick?: (entityType: string, entityId: string, entityName: string) => void,
) {
  const mentionMap = new Map<string, EntityMention>()
  for (const m of mentions) {
    mentionMap.set(`${m.type}:${m.name}`.toLowerCase(), m)
  }

  const pattern = /\[\[(actor|event|place):([^\]]+)\]\]/g
  const parts: Array<{ type: 'text'; content: string } | { type: 'entity'; entityType: string; name: string; mention: EntityMention | null }> = []
  let lastIndex = 0

  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'text', content: text.slice(lastIndex, match.index) })
    }
    const entityType = match[1]
    const entityName = match[2]
    const mention = mentionMap.get(`${entityType}:${entityName}`.toLowerCase()) || null
    parts.push({ type: 'entity', entityType, name: entityName, mention })
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < text.length) {
    parts.push({ type: 'text', content: text.slice(lastIndex) })
  }

  return parts.map((part, i) => {
    if (part.type === 'text') return <span key={i}>{part.content}</span>
    const color = ENTITY_COLORS[part.entityType] || 'var(--gold)'
    const hasId = part.mention?.canonical_id
    const aka = part.mention?.also_known_as
    const tooltip = aka && aka.length > 0
      ? `${part.name} (also: ${aka.join(', ')})`
      : part.name
    return (
      <span
        key={i}
        title={tooltip}
        onClick={hasId && onEntityClick ? () => onEntityClick(part.entityType, part.mention!.canonical_id!, part.name) : undefined}
        style={{
          color,
          fontWeight: 600,
          cursor: hasId ? 'pointer' : 'default',
          borderBottom: hasId ? `1px dotted ${color}` : 'none',
          transition: 'opacity 0.15s',
        }}
        onMouseOver={e => { if (hasId) (e.target as HTMLElement).style.opacity = '0.8' }}
        onMouseOut={e => { (e.target as HTMLElement).style.opacity = '1' }}
      >
        {part.name}
      </span>
    )
  })
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

export default function NarrativeReader({ chapters, activeChapterId, onChapterInView, onEntityClick }: Props) {
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

  const epochPartNumbers = useMemo(() => {
    let partNum = 0
    let lastEpochId: string | null = null
    const map = new Map<string, number>()
    for (const ch of chapters) {
      if (ch.epoch_id !== lastEpochId) {
        partNum++
        lastEpochId = ch.epoch_id
      }
      map.set(ch.id, partNum)
    }
    return map
  }, [chapters])

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
                    Part {epochPartNumbers.get(ch.id) || ''}
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
                {ch.time_hint && (
                  <div style={{ fontSize: 13, color: 'var(--gold)', fontWeight: 500 }}>
                    {ch.time_hint}
                  </div>
                )}
                {ch.chapter_summary && (
                  <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4, fontStyle: 'italic', lineHeight: 1.5 }}>
                    {ch.chapter_summary}
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
                    {parseNarrativeWithEntities(para, ch.entity_mentions || [], onEntityClick)}
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

import { useRef, useEffect, useCallback, useMemo, useState } from 'react'
import { api } from '../../api'
import type { StoryChapter, EntityMention, CultureVariant } from '../../api'

interface Props {
  chapters: StoryChapter[]
  activeChapterId: string | null
  onChapterInView: (id: string) => void
  onEntityClick?: (entityType: string, entityId: string, entityName: string) => void
  onCultureSelect?: (variant: CultureVariant | null) => void
  isMobile?: boolean
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

function ChapterViewSelector({
  chapterId,
  selectedView,
  onViewChange,
}: {
  chapterId: string
  selectedView: string
  onViewChange: (view: string) => void
}) {
  const [variants, setVariants] = useState<CultureVariant[] | null>(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const dropdownRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setLoading(true)
    api.getCultureVariants(chapterId)
      .then(v => setVariants(v))
      .catch(() => setVariants(null))
      .finally(() => setLoading(false))
  }, [chapterId])

  useEffect(() => {
    if (open && searchRef.current) searchRef.current.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  if (loading || !variants || variants.length === 0) return null

  const filtered = search
    ? variants.filter(v => v.culture.toLowerCase().includes(search.toLowerCase()))
    : variants

  return (
    <div style={{ position: 'relative', marginTop: 8 }} ref={dropdownRef}>
      <button
        onClick={() => { setOpen(!open); setSearch('') }}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '5px 12px',
          background: selectedView === 'unified' ? 'var(--bg-secondary)' : 'rgba(212, 168, 83, 0.12)',
          border: `1px solid ${selectedView === 'unified' ? 'var(--border)' : 'var(--gold)'}`,
          borderRadius: 16,
          cursor: 'pointer',
          fontSize: 12,
          color: selectedView === 'unified' ? 'var(--text-secondary)' : 'var(--gold)',
          fontWeight: 500,
        }}
      >
        <span>{selectedView === 'unified' ? 'Unified History' : selectedView}</span>
        <span style={{ fontSize: 10 }}>{open ? '\u25B2' : '\u25BC'}</span>
        <span style={{
          fontSize: 10,
          padding: '1px 5px',
          background: 'var(--bg-tertiary)',
          borderRadius: 8,
          color: 'var(--text-muted)',
        }}>
          {variants.length}
        </span>
      </button>

      {open && (
        <div style={{
          position: 'absolute',
          top: '100%',
          left: 0,
          marginTop: 4,
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
          zIndex: 100,
          width: 280,
          maxHeight: 400,
          display: 'flex',
          flexDirection: 'column',
        }}>
          <div style={{ padding: '8px 10px', borderBottom: '1px solid var(--border)' }}>
            <input
              ref={searchRef}
              type="text"
              placeholder="Search cultures..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              style={{
                width: '100%',
                padding: '6px 10px',
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border)',
                borderRadius: 6,
                fontSize: 12,
                color: 'var(--text-primary)',
                outline: 'none',
              }}
            />
          </div>

          <div style={{ overflow: 'auto', flex: 1 }}>
            <button
              onClick={() => { onViewChange('unified'); setOpen(false); setSearch('') }}
              style={{
                width: '100%',
                padding: '10px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                background: selectedView === 'unified' ? 'var(--bg-tertiary)' : 'transparent',
                border: 'none',
                borderBottom: '1px solid var(--border)',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--gold)' }}>
                Unified History
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                All traditions woven
              </span>
            </button>

            {filtered.map(v => (
              <button
                key={v.culture}
                onClick={() => { onViewChange(v.culture); setOpen(false); setSearch('') }}
                style={{
                  width: '100%',
                  padding: '8px 14px',
                  display: 'flex',
                  alignItems: 'baseline',
                  gap: 8,
                  background: selectedView === v.culture ? 'var(--bg-tertiary)' : 'transparent',
                  border: 'none',
                  borderBottom: '1px solid var(--border)',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span style={{
                  fontSize: 13,
                  color: selectedView === v.culture ? 'var(--text-primary)' : 'var(--text-secondary)',
                  fontWeight: selectedView === v.culture ? 500 : 400,
                }}>
                  {v.culture}
                </span>
              </button>
            ))}

            {filtered.length === 0 && (
              <div style={{ padding: '16px 14px', color: 'var(--text-muted)', fontSize: 12, textAlign: 'center' }}>
                No matching cultures
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function NarrativeReader({ chapters, activeChapterId, onChapterInView, onEntityClick, onCultureSelect, isMobile }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [currentView, setCurrentView] = useState('unified')
  const [loadingCulture, setLoadingCulture] = useState<string | null>(null)
  const [cultureDetail, setCultureDetail] = useState<CultureVariant | null>(null)

  const chapterIdx = chapters.findIndex(c => c.id === activeChapterId)
  const ch = chapterIdx >= 0 ? chapters[chapterIdx] : null

  const epochPartNumber = useMemo(() => {
    let partNum = 0
    let lastEpochId: string | null = null
    for (const c of chapters) {
      if (c.epoch_id !== lastEpochId) {
        partNum++
        lastEpochId = c.epoch_id
      }
      if (c.id === activeChapterId) return partNum
    }
    return 1
  }, [chapters, activeChapterId])

  useEffect(() => {
    setCurrentView('unified')
    setCultureDetail(null)
    setLoadingCulture(null)
    onCultureSelect?.(null)
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [activeChapterId])

  const handleViewChange = useCallback((view: string) => {
    setCurrentView(view)
    if (view === 'unified') {
      setCultureDetail(null)
      onCultureSelect?.(null)
      setLoadingCulture(null)
    } else if (ch) {
      setLoadingCulture(view)
      api.getStoryCultureDetail(ch.id, view).then(detail => {
        setCultureDetail(detail)
        onCultureSelect?.(detail)
        setLoadingCulture(null)
      }).catch(() => {
        setCultureDetail(null)
        setLoadingCulture(null)
      })
    }
  }, [ch, onCultureSelect])

  const goPrev = () => {
    if (chapterIdx > 0) onChapterInView(chapters[chapterIdx - 1].id)
  }
  const goNext = () => {
    if (chapterIdx < chapters.length - 1) onChapterInView(chapters[chapterIdx + 1].id)
  }

  if (!ch) {
    return (
      <div style={{ flex: 1, minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
        Select a chapter
      </div>
    )
  }

  const showEpochHeader = chapterIdx === 0 || ch.epoch_id !== chapters[chapterIdx - 1].epoch_id

  return (
    <div
      ref={scrollRef}
      style={{
        flex: 1,
        minHeight: 0,
        overflow: 'auto',
        background: 'var(--bg-primary)',
      }}
    >
      <div style={{ maxWidth: 720, margin: '0 auto', padding: isMobile ? '24px 16px 80px' : '40px 24px 80px' }}>
        {/* Epoch header */}
        {showEpochHeader && (
          <div style={{
            textAlign: 'center',
            padding: '20px 0 32px',
          }}>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 3,
              color: 'var(--gold)',
              marginBottom: 8,
            }}>
              Part {epochPartNumber}
            </div>
            <h1 style={{
              fontSize: isMobile ? 22 : 28,
              fontWeight: 700,
              color: 'var(--text-primary)',
              fontFamily: "'Georgia', 'Times New Roman', serif",
              lineHeight: 1.3,
            }}>
              {ch.epoch_title}
            </h1>
          </div>
        )}

        {/* Chapter header */}
        <div style={{ marginBottom: 24 }}>
          <h2 style={{
            fontSize: isMobile ? 18 : 20,
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
          {ch.chapter_summary && currentView === 'unified' && (
            <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4, fontStyle: 'italic', lineHeight: 1.5 }}>
              {ch.chapter_summary}
            </div>
          )}
          <ChapterViewSelector
            chapterId={ch.id}
            selectedView={currentView}
            onViewChange={handleViewChange}
          />
        </div>

        {/* Chapter content */}
        {currentView === 'unified' ? (
          <>
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
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
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
          </>
        ) : loadingCulture ? (
          <div style={{ padding: 40, color: 'var(--text-muted)', textAlign: 'center', fontSize: 14 }}>
            Loading {loadingCulture} tradition...
          </div>
        ) : cultureDetail ? (
          <div>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 2,
              color: 'var(--gold)',
              marginBottom: 8,
              paddingBottom: 8,
              borderBottom: '1px solid var(--border)',
            }}>
              {cultureDetail.culture} Tradition &mdash; {ch.chapter_title}
            </div>

            {/* Figures/entities from this culture relevant to the chapter */}
            {cultureDetail.actors.length > 0 && (
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>
                  Key figures in this tradition:
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 16 }}>
                  {cultureDetail.actors.slice(0, 12).map(a => (
                    <span key={a.id} style={{
                      padding: '3px 10px',
                      background: 'rgba(212, 168, 83, 0.1)',
                      border: '1px solid rgba(212, 168, 83, 0.25)',
                      borderRadius: 12,
                      fontSize: 12,
                      color: 'var(--gold)',
                    }}>
                      {a.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* Narrative-style rendering of source texts in the center */}
            {cultureDetail.source_texts.length > 0 ? (
              <div style={{
                fontSize: 16,
                lineHeight: 1.85,
                color: 'var(--text-primary)',
                fontFamily: "'Georgia', 'Times New Roman', serif",
              }}>
                {cultureDetail.source_texts.map((src, i) => (
                  <div key={i} style={{ marginBottom: 32 }}>
                    <div style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: 'var(--gold)',
                      marginBottom: 12,
                      fontFamily: "'Inter', sans-serif",
                    }}>
                      From: {src.title}
                    </div>
                    {src.text.split('\n\n').map((para, pIdx) => (
                      <p key={pIdx} style={{ marginBottom: 16 }}>{para}</p>
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{
                padding: 40,
                color: 'var(--text-muted)',
                textAlign: 'center',
                fontSize: 14,
              }}>
                No source texts found for this culture on this chapter.
              </div>
            )}
          </div>
        ) : (
          <div style={{ padding: 40, color: 'var(--text-muted)', textAlign: 'center', fontSize: 14 }}>
            Select a tradition above to view its account
          </div>
        )}

        {/* Prev / Next navigation */}
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginTop: 40,
          paddingTop: 24,
          borderTop: '1px solid var(--border)',
        }}>
          <button
            onClick={goPrev}
            disabled={chapterIdx <= 0}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 16px',
              background: chapterIdx > 0 ? 'var(--bg-secondary)' : 'transparent',
              border: `1px solid ${chapterIdx > 0 ? 'var(--border)' : 'transparent'}`,
              borderRadius: 8,
              cursor: chapterIdx > 0 ? 'pointer' : 'default',
              color: chapterIdx > 0 ? 'var(--text-secondary)' : 'var(--bg-tertiary)',
              fontSize: 13,
              maxWidth: '45%',
              textAlign: 'left',
            }}
          >
            <span style={{ fontSize: 16 }}>&larr;</span>
            <span style={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {chapterIdx > 0 ? chapters[chapterIdx - 1].chapter_title : ''}
            </span>
          </button>

          <span style={{ fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 }}>
            {chapterIdx + 1} / {chapters.length}
          </span>

          <button
            onClick={goNext}
            disabled={chapterIdx >= chapters.length - 1}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '10px 16px',
              background: chapterIdx < chapters.length - 1 ? 'var(--bg-secondary)' : 'transparent',
              border: `1px solid ${chapterIdx < chapters.length - 1 ? 'var(--border)' : 'transparent'}`,
              borderRadius: 8,
              cursor: chapterIdx < chapters.length - 1 ? 'pointer' : 'default',
              color: chapterIdx < chapters.length - 1 ? 'var(--text-secondary)' : 'var(--bg-tertiary)',
              fontSize: 13,
              maxWidth: '45%',
              textAlign: 'right',
            }}
          >
            <span style={{
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>
              {chapterIdx < chapters.length - 1 ? chapters[chapterIdx + 1].chapter_title : ''}
            </span>
            <span style={{ fontSize: 16 }}>&rarr;</span>
          </button>
        </div>
      </div>
    </div>
  )
}

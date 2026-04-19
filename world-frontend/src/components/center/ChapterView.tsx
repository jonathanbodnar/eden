import { useState } from 'react'
import { useWorldContext } from '../../context/WorldContext'
import VideoPlayer from './VideoPlayer'
import EntityDetailModal from './EntityDetailModal'

function formatYear(y: number | null): string {
  if (y === null) return '?'
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

export default function ChapterView() {
  const { chapterDetail, narration, epochOverview, selectEntity, activeEntityId, selectChapter } = useWorldContext()
  const [modalEntity, setModalEntity] = useState<{ type: 'actor' | 'event' | 'place'; id: string } | null>(null)
  if (!chapterDetail) return null

  const { actors, events, places } = chapterDetail

  const handleEntityClick = (type: 'chapter' | 'event' | 'actor' | 'place', id: string) => {
    if (type === 'chapter') return
    setModalEntity({ type: type as 'actor' | 'event' | 'place', id })
    selectEntity(type, id)
  }

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      background: `
        radial-gradient(ellipse at 40% 20%, rgba(99, 102, 241, 0.05) 0%, transparent 50%),
        var(--bg-primary)
      `,
    }}>
      <div style={{
        padding: '20px 28px 14px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
        animation: 'fadeIn 0.3s',
      }}>
        <div style={{
          fontSize: '10px',
          color: 'var(--gold)',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          marginBottom: '4px',
        }}>
          {epochOverview?.epoch.title} · {formatYear(chapterDetail.time_start)} — {formatYear(chapterDetail.time_end)}
        </div>
        <h1 style={{
          fontSize: '20px',
          fontWeight: 700,
          color: 'var(--text-primary)',
          marginBottom: '6px',
        }}>
          {chapterDetail.title}
        </h1>
        {chapterDetail.chapter_summary && (
          <p style={{
            fontSize: '12px',
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
            maxWidth: '650px',
          }}>
            {chapterDetail.chapter_summary}
          </p>
        )}
      </div>

      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 28px 28px',
      }}>
        <VideoPlayer />

        {narration && (narration.intro_summary || narration.core_summary) && (
          <div style={{
            marginBottom: '20px',
            padding: '14px 16px',
            background: 'linear-gradient(135deg, rgba(212, 168, 83, 0.08), rgba(99, 102, 241, 0.04))',
            border: '1px solid var(--border)',
            borderRadius: '10px',
            animation: 'slideUp 0.4s',
          }}>
            <div style={{
              fontSize: '10px',
              fontWeight: 600,
              color: 'var(--gold)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: '8px',
            }}>
              Narration
            </div>
            {narration.intro_summary && (
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.6, marginBottom: '6px' }}>
                {narration.intro_summary}
              </p>
            )}
            {narration.core_summary && (
              <p style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: 1.6 }}>
                {narration.core_summary}
              </p>
            )}
          </div>
        )}

        {actors.length > 0 && (
          <EntitySection title="Key Actors" items={actors.map(a => ({
            id: a.id,
            entityType: 'actor' as const,
            name: a.canonical_name,
            type: a.actor_type,
            summary: a.summary,
            timeLabel: a.time_start !== null ? `${formatYear(a.time_start)}${a.time_end !== null && a.time_end !== a.time_start ? ` — ${formatYear(a.time_end)}` : ''}` : null,
          }))} color="var(--accent)" onSelect={handleEntityClick} activeEntityId={activeEntityId} />
        )}

        {events.length > 0 && (
          <EntitySection title="Events" items={events.map(e => ({
            id: e.id,
            entityType: 'event' as const,
            name: e.canonical_name,
            type: e.event_type,
            summary: e.summary,
            timeLabel: e.time_start !== null ? `${formatYear(e.time_start)}${e.time_end !== null && e.time_end !== e.time_start ? ` — ${formatYear(e.time_end)}` : ''}` : null,
          }))} color="var(--warning)" onSelect={handleEntityClick} activeEntityId={activeEntityId} />
        )}

        {places.length > 0 && (
          <EntitySection title="Places" items={places.map(p => ({
            id: p.id,
            entityType: 'place' as const,
            name: p.canonical_name,
            type: p.place_type,
            summary: p.summary,
            timeLabel: null,
          }))} color="var(--success)" onSelect={handleEntityClick} activeEntityId={activeEntityId} />
        )}

        {actors.length === 0 && events.length === 0 && places.length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: '32px',
            color: 'var(--text-muted)',
            fontSize: '12px',
          }}>
            No entities linked to this chapter yet. Run the synthesis pipeline to populate.
          </div>
        )}
      </div>

      {modalEntity && (
        <EntityDetailModal
          entityType={modalEntity.type}
          entityId={modalEntity.id}
          onClose={() => setModalEntity(null)}
          onChapterClick={(chapterId) => {
            setModalEntity(null)
            selectChapter(chapterId)
          }}
        />
      )}
    </div>
  )
}

function EntitySection({ title, items, color, onSelect, activeEntityId }: {
  title: string
  items: { id: string; entityType: 'actor' | 'event' | 'place'; name: string; type: string; summary: string | null; timeLabel: string | null }[]
  color: string
  onSelect: (type: 'chapter' | 'event' | 'actor' | 'place', id: string) => void
  activeEntityId: string | null
}) {
  return (
    <div style={{ marginBottom: '18px', animation: 'slideUp 0.4s' }}>
      <h2 style={{
        fontSize: '11px',
        fontWeight: 600,
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        marginBottom: '8px',
      }}>
        {title} ({items.length})
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: '8px' }}>
        {items.map((item) => {
          const isActive = item.id === activeEntityId
          return (
            <div
              key={item.id}
              onClick={() => onSelect(item.entityType, item.id)}
              style={{
                background: isActive ? 'rgba(99, 102, 241, 0.08)' : 'var(--bg-tertiary)',
                border: `1px solid ${isActive ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: '8px',
                padding: '10px 12px',
                borderLeft: `3px solid ${color}`,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '6px' }}>
                <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {item.name}
                </span>
                {item.timeLabel && (
                  <span style={{ fontSize: '9px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
                    {item.timeLabel}
                  </span>
                )}
              </div>
              <div style={{ fontSize: '10px', color, textTransform: 'capitalize', fontWeight: 500, marginTop: '1px' }}>
                {item.type.replace(/_/g, ' ')}
              </div>
              {item.summary && (
                <p style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.4, marginTop: '4px' }}>
                  {item.summary.length > 140 ? item.summary.slice(0, 140) + '...' : item.summary}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

import { useState } from 'react'
import { useWorldContext } from '../../context/WorldContext'
import type { Actor, CanonEvent, Place } from '../../api'
import EntityDetailModal from './EntityDetailModal'

function formatYear(y: number | null): string {
  if (y === null) return '?'
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

function EntityCard({ name, type, summary, timeStart, timeEnd, color, onClick }: {
  name: string; type: string; summary: string | null; timeStart: number | null; timeEnd: number | null; color: string; onClick?: () => void
}) {
  return (
    <div onClick={onClick} style={{
      background: 'var(--bg-tertiary)',
      border: '1px solid var(--border)',
      borderRadius: '8px',
      padding: '12px',
      borderLeft: `3px solid ${color}`,
      transition: 'border-color 0.2s',
      cursor: onClick ? 'pointer' : 'default',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: '12px',
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: '2px',
          }}>
            {name}
          </div>
          <div style={{
            fontSize: '10px',
            color,
            textTransform: 'capitalize',
            fontWeight: 500,
          }}>
            {type.replace(/_/g, ' ')}
          </div>
        </div>
        {(timeStart !== null || timeEnd !== null) && (
          <span style={{
            fontSize: '9px',
            color: 'var(--text-muted)',
            whiteSpace: 'nowrap',
            paddingTop: '2px',
          }}>
            {formatYear(timeStart)}{timeEnd !== null && timeEnd !== timeStart ? ` — ${formatYear(timeEnd)}` : ''}
          </span>
        )}
      </div>
      {summary && (
        <p style={{
          fontSize: '11px',
          color: 'var(--text-secondary)',
          lineHeight: 1.5,
          marginTop: '6px',
        }}>
          {summary.length > 180 ? summary.slice(0, 180) + '...' : summary}
        </p>
      )}
    </div>
  )
}

export default function CultureView() {
  const { activeCulture, cultureDetail, cultureLoading, epochOverview, selectCulture, selectChapter } = useWorldContext()
  const [modalEntity, setModalEntity] = useState<{ type: 'actor' | 'event' | 'place'; id: string } | null>(null)

  if (cultureLoading) {
    return (
      <div style={{
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg-primary)',
      }}>
        <span style={{ fontSize: '12px', color: 'var(--text-muted)', animation: 'pulse 1s infinite' }}>
          Loading {activeCulture}...
        </span>
      </div>
    )
  }

  if (!cultureDetail || !activeCulture) return null

  const { actors, events, places, sources, images } = cultureDetail
  const epochTitle = epochOverview?.epoch.title || ''

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
      background: `
        radial-gradient(ellipse at 20% 30%, rgba(212, 168, 83, 0.05) 0%, transparent 50%),
        var(--bg-primary)
      `,
    }}>
      <div style={{
        padding: '16px 28px 12px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        animation: 'fadeIn 0.3s',
      }}>
        <button
          onClick={() => selectCulture(null)}
          style={{
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            padding: '6px 10px',
            cursor: 'pointer',
            fontSize: '11px',
            color: 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          ← Back to {epochTitle}
        </button>
        <div>
          <h1 style={{ fontSize: '18px', fontWeight: 700, color: 'var(--text-primary)' }}>
            {activeCulture}
          </h1>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '1px' }}>
            {actors.length} actors · {events.length} events · {places.length} places · {sources.length} sources
          </div>
        </div>
      </div>

      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '16px 28px 28px',
      }}>
        {actors.length > 0 && (
          <Section title="Actors & Figures" count={actors.length}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '8px' }}>
              {actors.map((a: Actor) => (
                <EntityCard key={a.id} name={a.canonical_name} type={a.actor_type} summary={a.summary} timeStart={a.time_start} timeEnd={a.time_end} color="var(--accent)" onClick={() => setModalEntity({ type: 'actor', id: a.id })} />
              ))}
            </div>
          </Section>
        )}

        {events.length > 0 && (
          <Section title="Events" count={events.length}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '8px' }}>
              {events.map((e: CanonEvent) => (
                <EntityCard key={e.id} name={e.canonical_name} type={e.event_type} summary={e.summary} timeStart={e.time_start} timeEnd={e.time_end} color="var(--warning)" onClick={() => setModalEntity({ type: 'event', id: e.id })} />
              ))}
            </div>
          </Section>
        )}

        {places.length > 0 && (
          <Section title="Places" count={places.length}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '8px' }}>
              {places.map((p: Place) => (
                <EntityCard key={p.id} name={p.canonical_name} type={p.place_type} summary={p.summary} timeStart={null} timeEnd={null} color="var(--success)" onClick={() => setModalEntity({ type: 'place', id: p.id })} />
              ))}
            </div>
          </Section>
        )}

        {images.length > 0 && (
          <Section title="Visual Evidence" count={images.length}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: '8px' }}>
              {images.map(img => (
                <div key={img.id} style={{
                  borderRadius: '8px',
                  overflow: 'hidden',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-tertiary)',
                }}>
                  {img.image_url ? (
                    <img src={img.image_url} alt={img.caption || ''} style={{
                      width: '100%',
                      height: '120px',
                      objectFit: 'cover',
                    }} />
                  ) : (
                    <div style={{
                      width: '100%',
                      height: '120px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: 'var(--text-muted)',
                      fontSize: '10px',
                    }}>
                      No image
                    </div>
                  )}
                  {img.caption && (
                    <div style={{
                      padding: '6px 8px',
                      fontSize: '10px',
                      color: 'var(--text-secondary)',
                      lineHeight: 1.3,
                    }}>
                      {img.caption.slice(0, 80)}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </Section>
        )}

        {sources.length > 0 && (
          <Section title="Source Texts" count={sources.length}>
            {sources.slice(0, 15).map(src => (
              <div key={src.id} style={{
                background: 'var(--bg-tertiary)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                padding: '10px 12px',
                marginBottom: '6px',
              }}>
                <div style={{ fontSize: '12px', fontWeight: 500, color: 'var(--text-primary)' }}>
                  {src.title || 'Untitled'}
                </div>
                {src.excerpt && (
                  <p style={{
                    fontSize: '11px',
                    color: 'var(--text-secondary)',
                    lineHeight: 1.5,
                    marginTop: '4px',
                    fontStyle: 'italic',
                    borderLeft: '2px solid var(--gold)',
                    paddingLeft: '8px',
                  }}>
                    {src.excerpt.slice(0, 200)}{src.excerpt.length > 200 ? '...' : ''}
                  </p>
                )}
                {src.source_type && (
                  <span style={{ fontSize: '9px', color: 'var(--text-muted)', textTransform: 'capitalize' }}>
                    {src.source_type.replace(/_/g, ' ')}
                  </span>
                )}
              </div>
            ))}
          </Section>
        )}

        {actors.length === 0 && events.length === 0 && places.length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: '40px',
            color: 'var(--text-muted)',
            fontSize: '12px',
          }}>
            Detailed data for {activeCulture} is still being synthesized.
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

function Section({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: '20px', animation: 'slideUp 0.4s' }}>
      <h2 style={{
        fontSize: '11px',
        fontWeight: 600,
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.08em',
        marginBottom: '10px',
      }}>
        {title} ({count})
      </h2>
      {children}
    </div>
  )
}

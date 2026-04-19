import { useEffect, useState, useCallback } from 'react'
import { api } from '../../api'
import type { EntityDetail } from '../../api'

function formatYear(y: number | null): string {
  if (y === null) return '?'
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

const TYPE_COLORS: Record<string, string> = {
  actor: 'var(--accent)',
  event: 'var(--warning)',
  place: 'var(--success)',
}

const TYPE_LABELS: Record<string, string> = {
  actor: 'Actor',
  event: 'Event',
  place: 'Place',
}

export default function EntityDetailModal({ entityType, entityId, onClose, onChapterClick }: {
  entityType: 'actor' | 'event' | 'place'
  entityId: string
  onClose: () => void
  onChapterClick?: (chapterId: string) => void
}) {
  const [detail, setDetail] = useState<EntityDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [imgPage, setImgPage] = useState(0)
  const IMGS_PER_PAGE = 12

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.getEntityDetail(entityType, entityId)
      .then(d => { if (!cancelled) { setDetail(d); setLoading(false) } })
      .catch(e => { if (!cancelled) { setError(e.message); setLoading(false) } })
    return () => { cancelled = true }
  }, [entityType, entityId])

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') onClose()
  }, [onClose])

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  const color = TYPE_COLORS[entityType] || 'var(--accent)'
  const typeLabel = TYPE_LABELS[entityType] || entityType

  const entitySubtype = detail
    ? (detail.actor_type || detail.event_type || detail.place_type || 'unknown').replace(/_/g, ' ')
    : ''

  const visibleImages = detail?.images.slice(imgPage * IMGS_PER_PAGE, (imgPage + 1) * IMGS_PER_PAGE) || []
  const totalImgPages = detail ? Math.ceil(detail.images.length / IMGS_PER_PAGE) : 0

  return (
    <div onClick={onClose} style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      animation: 'fadeIn 0.2s',
    }}>
      <div onClick={e => e.stopPropagation()} style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: '14px',
        width: '90vw', maxWidth: '780px',
        maxHeight: '88vh',
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: '0 24px 64px rgba(0,0,0,0.5)',
      }}>
        {/* Header */}
        <div style={{
          padding: '20px 24px 16px',
          borderBottom: '1px solid var(--border)',
          background: `linear-gradient(135deg, rgba(${entityType === 'actor' ? '99,102,241' : entityType === 'event' ? '245,158,11' : '16,185,129'},0.06), transparent)`,
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{
                  fontSize: '9px', fontWeight: 700, textTransform: 'uppercase',
                  letterSpacing: '0.1em', color, background: `${color}15`,
                  padding: '2px 8px', borderRadius: '4px',
                }}>
                  {typeLabel}
                </span>
                <span style={{
                  fontSize: '9px', fontWeight: 600, textTransform: 'capitalize',
                  color: 'var(--text-muted)', letterSpacing: '0.05em',
                }}>
                  {entitySubtype}
                </span>
              </div>
              <h2 style={{ fontSize: '22px', fontWeight: 700, color: 'var(--text-primary)', margin: 0 }}>
                {loading ? 'Loading...' : detail?.canonical_name || 'Unknown'}
              </h2>
              {detail && (detail.time_start !== null || detail.time_end !== null) && (
                <div style={{ fontSize: '11px', color: 'var(--gold)', marginTop: '4px', fontWeight: 500 }}>
                  {formatYear(detail.time_start)}
                  {detail.time_end !== null && detail.time_end !== detail.time_start && ` — ${formatYear(detail.time_end)}`}
                </div>
              )}
            </div>
            <button onClick={onClose} style={{
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              fontSize: '20px', cursor: 'pointer', padding: '4px 8px', lineHeight: 1,
            }}>
              ✕
            </button>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px 24px 24px' }}>
          {loading && (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)' }}>
              Loading entity details...
            </div>
          )}
          {error && (
            <div style={{ textAlign: 'center', padding: '40px', color: '#ef4444' }}>
              {error}
            </div>
          )}
          {detail && !loading && (
            <>
              {/* Summary */}
              {detail.summary && (
                <Section title="Summary">
                  <p style={{ fontSize: '13px', color: 'var(--text-secondary)', lineHeight: 1.7, margin: 0 }}>
                    {detail.summary}
                  </p>
                </Section>
              )}

              {/* Confidence */}
              {detail.merge_confidence !== null && detail.merge_confidence > 0 && (
                <div style={{
                  display: 'inline-flex', gap: '6px', alignItems: 'center',
                  fontSize: '10px', color: 'var(--text-muted)', marginBottom: '16px',
                }}>
                  <span>Confidence:</span>
                  <div style={{
                    width: '80px', height: '4px', borderRadius: '2px',
                    background: 'var(--bg-tertiary)', overflow: 'hidden',
                  }}>
                    <div style={{
                      width: `${(detail.merge_confidence * 100)}%`, height: '100%',
                      background: color, borderRadius: '2px',
                    }} />
                  </div>
                  <span>{(detail.merge_confidence * 100).toFixed(0)}%</span>
                </div>
              )}

              {/* Images */}
              {detail.images.length > 0 && (
                <Section title={`Images (${detail.images.length})`}>
                  <div style={{
                    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
                    gap: '8px', marginBottom: totalImgPages > 1 ? '8px' : 0,
                  }}>
                    {visibleImages.map(img => (
                      <div key={img.id} style={{
                        aspectRatio: '1', borderRadius: '6px', overflow: 'hidden',
                        border: '1px solid var(--border)', background: 'var(--bg-tertiary)',
                      }}>
                        {img.image_url && (
                          <img
                            src={img.image_url}
                            alt={img.caption || img.alt_text || ''}
                            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                            loading="lazy"
                          />
                        )}
                      </div>
                    ))}
                  </div>
                  {totalImgPages > 1 && (
                    <div style={{ display: 'flex', gap: '8px', alignItems: 'center', justifyContent: 'center' }}>
                      <PageBtn disabled={imgPage === 0} onClick={() => setImgPage(p => p - 1)}>← Prev</PageBtn>
                      <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                        {imgPage + 1} / {totalImgPages}
                      </span>
                      <PageBtn disabled={imgPage >= totalImgPages - 1} onClick={() => setImgPage(p => p + 1)}>Next →</PageBtn>
                    </div>
                  )}
                </Section>
              )}

              {/* Linked Chapters */}
              {detail.chapters.length > 0 && (
                <Section title={`Appears in Chapters (${detail.chapters.length})`}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {detail.chapters.map(ch => (
                      <div
                        key={ch.id}
                        onClick={() => onChapterClick?.(ch.id)}
                        style={{
                          padding: '8px 12px', borderRadius: '6px',
                          background: 'var(--bg-tertiary)', border: '1px solid var(--border)',
                          cursor: onChapterClick ? 'pointer' : 'default',
                          transition: 'border-color 0.15s',
                        }}
                      >
                        <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                          {ch.title}
                        </div>
                        <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>
                          {ch.time_start !== null && formatYear(ch.time_start)}
                          {ch.time_end !== null && ch.time_end !== ch.time_start && ` — ${formatYear(ch.time_end)}`}
                          {ch.focus_reason && <span style={{ marginLeft: '8px', color: 'var(--text-secondary)' }}>· {ch.focus_reason}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {/* Source Excerpts */}
              {detail.source_excerpts.length > 0 && (
                <Section title={`Primary Sources (${detail.source_excerpts.length})`}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {detail.source_excerpts.map((src, i) => (
                      <div key={i} style={{
                        padding: '12px 14px', borderRadius: '8px',
                        background: 'var(--bg-tertiary)', border: '1px solid var(--border)',
                        borderLeft: `3px solid ${color}`,
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '8px' }}>
                          <div>
                            <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)' }}>
                              {src.title || 'Untitled Source'}
                            </div>
                            <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>
                              {[src.culture, src.category?.replace(/_/g, ' ')].filter(Boolean).join(' · ')}
                              {src.dates.length > 0 && (
                                <span style={{ marginLeft: '6px' }}>
                                  · {src.dates.map(d => d.date_label || `${formatYear(d.date_start)}`).join(', ')}
                                </span>
                              )}
                            </div>
                          </div>
                          <span style={{
                            fontSize: '9px', color: 'var(--text-muted)', whiteSpace: 'nowrap',
                            background: 'var(--bg-primary)', padding: '2px 6px', borderRadius: '3px',
                          }}>
                            {src.support_type.replace(/.*\./, '').replace(/_/g, ' ')}
                          </span>
                        </div>
                        {src.excerpt && (
                          <p style={{
                            fontSize: '11px', color: 'var(--text-secondary)',
                            lineHeight: 1.6, marginTop: '8px', marginBottom: 0,
                            whiteSpace: 'pre-wrap',
                          }}>
                            {src.excerpt.length > 500 ? src.excerpt.slice(0, 500) + '...' : src.excerpt}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {/* Geo hints for places */}
              {entityType === 'place' && detail.geo_hint_json && Object.keys(detail.geo_hint_json).length > 0 && (
                <Section title="Geographic Information">
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {Object.entries(detail.geo_hint_json).map(([k, v]) => (
                      <div key={k} style={{
                        fontSize: '11px', padding: '4px 10px', borderRadius: '4px',
                        background: 'var(--bg-tertiary)', border: '1px solid var(--border)',
                      }}>
                        <span style={{ color: 'var(--text-muted)', marginRight: '4px' }}>{k}:</span>
                        <span style={{ color: 'var(--text-primary)' }}>{String(v)}</span>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              {detail.images.length === 0 && detail.chapters.length === 0 && detail.source_excerpts.length === 0 && !detail.summary && (
                <div style={{ textAlign: 'center', padding: '32px', color: 'var(--text-muted)', fontSize: '12px' }}>
                  No detailed information available yet. Data will populate as extraction completes.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: '20px' }}>
      <h3 style={{
        fontSize: '10px', fontWeight: 700, color: 'var(--text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '8px',
      }}>
        {title}
      </h3>
      {children}
    </div>
  )
}

function PageBtn({ children, disabled, onClick }: { children: React.ReactNode; disabled: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      fontSize: '10px', padding: '4px 10px', borderRadius: '4px',
      background: disabled ? 'transparent' : 'var(--bg-tertiary)',
      border: `1px solid ${disabled ? 'transparent' : 'var(--border)'}`,
      color: disabled ? 'var(--text-muted)' : 'var(--text-secondary)',
      cursor: disabled ? 'default' : 'pointer',
    }}>
      {children}
    </button>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { useWorldContext } from '../../context/WorldContext'
import { api, type ImageRecordDetail } from '../../api'

export default function EvidenceSection() {
  const { epochOverview, activeChapterId, activeCulture, cultureDetail } = useWorldContext()

  if (activeCulture && cultureDetail) {
    return <CultureEvidence />
  }

  if (activeChapterId) {
    return <ChapterEvidence />
  }

  if (epochOverview) {
    return <EpochProvenance />
  }

  return null
}

function EpochProvenance() {
  const { epochOverview } = useWorldContext()
  if (!epochOverview) return null

  const { epoch, cultures, total_sources, total_actors, total_events, total_places } = epochOverview

  return (
    <div style={{ padding: '12px 14px' }}>
      <div style={{
        padding: '12px',
        background: 'linear-gradient(135deg, rgba(212, 168, 83, 0.06), rgba(99, 102, 241, 0.03))',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginBottom: '12px',
      }}>
        <div style={{
          fontSize: '10px',
          fontWeight: 600,
          color: 'var(--gold)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: '6px',
        }}>
          How this epoch was constructed
        </div>
        <p style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          This view of <strong style={{ color: 'var(--text-primary)' }}>{epoch.title}</strong> was synthesized
          from {total_sources > 0 ? `${total_sources} primary source${total_sources !== 1 ? 's' : ''}` : 'available sources'}
          {cultures.length > 0 && ` spanning ${cultures.length} culture${cultures.length !== 1 ? 's' : ''}`}.
          {total_actors > 0 && ` ${total_actors} historical figures,`}
          {total_events > 0 && ` ${total_events} events,`}
          {total_places > 0 && ` and ${total_places} locations`}
          {(total_actors > 0 || total_events > 0 || total_places > 0) ? ' have been identified.' : ''}
          {' '}No external theories or interpretations are included — all data derives directly from artifacts, inscriptions, and textual records in our database.
        </p>
      </div>

      {cultures.length > 0 && (
        <div>
          <div style={{
            fontSize: '10px',
            fontWeight: 600,
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            marginBottom: '8px',
          }}>
            Cultures Represented
          </div>
          {cultures.map(c => (
            <div key={c.name} style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '6px 8px',
              borderRadius: '4px',
              marginBottom: '3px',
              background: 'var(--bg-tertiary)',
            }}>
              <span style={{ fontSize: '11px', color: 'var(--text-primary)' }}>{c.name}</span>
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                {c.source_count} src · {c.actor_count + c.event_count + c.place_count} entities
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ChapterEvidence() {
  const { sources, contexts, artifacts, images } = useWorldContext()
  const empty = sources.length === 0 && contexts.length === 0 && artifacts.length === 0 && images.length === 0

  if (empty) {
    return (
      <div style={{ padding: '24px 14px', color: 'var(--text-muted)', fontSize: '11px', textAlign: 'center' }}>
        No evidence data linked to this chapter yet.
      </div>
    )
  }

  return (
    <div style={{ padding: '10px 14px' }}>
      {sources.length > 0 && (
        <EvidenceGroup title={`Sources (${sources.length})`}>
          {sources.map(src => (
            <div key={src.id} style={{
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '10px',
              marginBottom: '6px',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-primary)', flex: 1 }}>
                  {src.title || 'Untitled'}
                </span>
                <span style={{
                  fontSize: '9px',
                  padding: '1px 5px',
                  borderRadius: '3px',
                  background: 'var(--accent-dim)',
                  color: 'var(--accent)',
                  fontWeight: 600,
                  marginLeft: '6px',
                }}>
                  {(src.relevance_weight * 100).toFixed(0)}%
                </span>
              </div>
              {src.excerpt && (
                <p style={{
                  fontSize: '10px',
                  color: 'var(--text-secondary)',
                  lineHeight: 1.5,
                  marginTop: '4px',
                  fontStyle: 'italic',
                  borderLeft: '2px solid var(--gold)',
                  paddingLeft: '6px',
                }}>
                  {src.excerpt.slice(0, 160)}{src.excerpt.length > 160 ? '...' : ''}
                </p>
              )}
            </div>
          ))}
        </EvidenceGroup>
      )}

      {artifacts.length > 0 && (
        <EvidenceGroup title={`Artifacts (${artifacts.length})`}>
          {artifacts.map(art => (
            <div key={art.id} style={{
              display: 'flex',
              gap: '8px',
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '8px',
              marginBottom: '6px',
            }}>
              {art.image_url && (
                <img src={art.image_url} alt={art.title || ''} style={{
                  width: '48px', height: '48px', objectFit: 'cover', borderRadius: '4px', border: '1px solid var(--border)',
                }} />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-primary)' }}>
                  {art.title || 'Untitled'}
                </div>
                {art.description && (
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', lineHeight: 1.4, marginTop: '2px' }}>
                    {art.description.slice(0, 100)}
                  </div>
                )}
                <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  {[art.location, art.date_label].filter(Boolean).join(' · ')}
                </div>
              </div>
            </div>
          ))}
        </EvidenceGroup>
      )}

      {images.length > 0 && (
        <ImageGallery images={images} />
      )}

      {contexts.length > 0 && (
        <EvidenceGroup title={`Contextual Statements (${contexts.length})`}>
          {contexts.slice(0, 10).map(ctx => (
            <div key={ctx.id} style={{
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '8px 10px',
              marginBottom: '4px',
              fontSize: '10px',
              color: 'var(--text-secondary)',
              lineHeight: 1.5,
            }}>
              {ctx.summary || ctx.artifact_description || 'Context reference'}
            </div>
          ))}
        </EvidenceGroup>
      )}
    </div>
  )
}

function CultureEvidence() {
  const { activeCulture, cultureDetail } = useWorldContext()
  if (!cultureDetail || !activeCulture) return null

  return (
    <div style={{ padding: '10px 14px' }}>
      <div style={{
        padding: '10px',
        background: 'linear-gradient(135deg, rgba(212, 168, 83, 0.06), transparent)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginBottom: '10px',
      }}>
        <div style={{ fontSize: '10px', fontWeight: 600, color: 'var(--gold)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '4px' }}>
          {activeCulture} — Source Evidence
        </div>
        <p style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
          {cultureDetail.sources.length} source{cultureDetail.sources.length !== 1 ? 's' : ''} from {activeCulture} tradition
          · {cultureDetail.actors.length} actors
          · {cultureDetail.events.length} events
          · {cultureDetail.places.length} places.
          All data from primary artifacts and inscriptions only.
        </p>
      </div>

      {cultureDetail.sources.length > 0 && (
        <EvidenceGroup title={`Sources (${cultureDetail.sources.length})`}>
          {cultureDetail.sources.slice(0, 12).map(src => (
            <div key={src.id} style={{
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '8px 10px',
              marginBottom: '4px',
            }}>
              <div style={{ fontSize: '11px', fontWeight: 500, color: 'var(--text-primary)' }}>
                {src.title || 'Untitled'}
              </div>
              {src.excerpt && (
                <p style={{ fontSize: '10px', color: 'var(--text-secondary)', fontStyle: 'italic', marginTop: '3px', lineHeight: 1.4 }}>
                  {src.excerpt.slice(0, 120)}
                </p>
              )}
            </div>
          ))}
        </EvidenceGroup>
      )}
    </div>
  )
}

function ImageGallery({ images }: { images: { id: string; image_url: string | null; caption: string | null }[] }) {
  const PAGE_SIZE = 30
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)
  const [modalImageId, setModalImageId] = useState<string | null>(null)
  const visible = images.slice(0, visibleCount)
  const remaining = images.length - visibleCount

  return (
    <>
      <EvidenceGroup title={`Images (${images.length})`}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '4px' }}>
          {visible.map(img => (
            <div
              key={img.id}
              onClick={() => setModalImageId(img.id)}
              style={{
                borderRadius: '5px', overflow: 'hidden', border: '1px solid var(--border)',
                background: 'var(--bg-tertiary)', cursor: 'pointer', transition: 'border-color 0.15s',
              }}
              onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--gold)')}
              onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            >
              {img.image_url ? (
                <img
                  src={img.image_url}
                  alt={img.caption || ''}
                  loading="lazy"
                  style={{ width: '100%', height: '70px', objectFit: 'cover', display: 'block' }}
                />
              ) : (
                <div style={{ width: '100%', height: '70px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '9px' }}>
                  No image
                </div>
              )}
            </div>
          ))}
        </div>
        {remaining > 0 && (
          <div
            onClick={() => setVisibleCount(prev => prev + PAGE_SIZE)}
            style={{
              textAlign: 'center',
              padding: '8px',
              cursor: 'pointer',
              fontSize: '10px',
              color: 'var(--accent)',
              fontWeight: 600,
              marginTop: '6px',
              borderRadius: '6px',
              border: '1px solid var(--border)',
              background: 'var(--bg-tertiary)',
            }}
          >
            Show more ({remaining} remaining)
          </div>
        )}
      </EvidenceGroup>

      {modalImageId && (
        <ImageRecordModal
          imageId={modalImageId}
          onClose={() => setModalImageId(null)}
        />
      )}
    </>
  )
}

function ImageRecordModal({ imageId, onClose }: { imageId: string; onClose: () => void }) {
  const [detail, setDetail] = useState<ImageRecordDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setError(null)
    api.getImageRecordDetail(imageId)
      .then(setDetail)
      .catch(err => setError(err.message || 'Failed to load record'))
      .finally(() => setLoading(false))
  }, [imageId])

  const handleBackdropClick = useCallback((e: React.MouseEvent) => {
    if (e.target === e.currentTarget) onClose()
  }, [onClose])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const overlayStyle: React.CSSProperties = {
    position: 'fixed', inset: 0, zIndex: 9999,
    background: 'rgba(0,0,0,0.85)', display: 'flex', alignItems: 'center', justifyContent: 'center',
    padding: '24px',
  }

  const modalStyle: React.CSSProperties = {
    background: 'var(--bg-secondary, #1a1a2e)', border: '1px solid var(--border)',
    borderRadius: '12px', maxWidth: '680px', width: '100%', maxHeight: '90vh',
    overflow: 'auto', position: 'relative',
  }

  const closeBtnStyle: React.CSSProperties = {
    position: 'absolute', top: '12px', right: '12px', background: 'rgba(255,255,255,0.08)',
    border: 'none', color: 'var(--text-secondary)', fontSize: '18px', width: '30px', height: '30px',
    borderRadius: '50%', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1,
  }

  const labelStyle: React.CSSProperties = {
    fontSize: '9px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase',
    letterSpacing: '0.06em', marginBottom: '2px',
  }

  const valueStyle: React.CSSProperties = {
    fontSize: '12px', color: 'var(--text-primary)', lineHeight: 1.5,
  }

  return (
    <div style={overlayStyle} onClick={handleBackdropClick}>
      <div style={modalStyle}>
        <button style={closeBtnStyle} onClick={onClose}>&times;</button>

        {loading && (
          <div style={{ padding: '48px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '12px' }}>
            Loading record...
          </div>
        )}

        {error && (
          <div style={{ padding: '48px', textAlign: 'center', color: '#ef4444', fontSize: '12px' }}>
            {error}
          </div>
        )}

        {detail && !loading && (
          <>
            {detail.image_url && (
              <img
                src={detail.image_url}
                alt={detail.caption || ''}
                style={{
                  width: '100%', maxHeight: '380px', objectFit: 'contain',
                  background: '#000', borderRadius: '12px 12px 0 0',
                }}
              />
            )}

            <div style={{ padding: '16px 20px 20px' }}>
              {detail.record_title && (
                <h3 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 4px', lineHeight: 1.3 }}>
                  {detail.record_title}
                </h3>
              )}

              {detail.caption && (
                <p style={{ fontSize: '11px', color: 'var(--text-secondary)', fontStyle: 'italic', margin: '0 0 12px', lineHeight: 1.5 }}>
                  {detail.caption}
                </p>
              )}

              <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px',
                padding: '12px', background: 'var(--bg-tertiary)', borderRadius: '8px',
                border: '1px solid var(--border)', marginBottom: '12px',
              }}>
                {detail.culture && (
                  <div>
                    <div style={labelStyle}>Culture</div>
                    <div style={valueStyle}>{detail.culture}</div>
                  </div>
                )}
                {detail.origin_place_name && (
                  <div>
                    <div style={labelStyle}>Origin</div>
                    <div style={valueStyle}>{detail.origin_place_name}</div>
                  </div>
                )}
                {detail.source_category && (
                  <div>
                    <div style={labelStyle}>Category</div>
                    <div style={valueStyle}>{detail.source_category}</div>
                  </div>
                )}
                {detail.language_family && (
                  <div>
                    <div style={labelStyle}>Language</div>
                    <div style={valueStyle}>{detail.language_family}</div>
                  </div>
                )}
                {detail.trusted_source_name && (
                  <div>
                    <div style={labelStyle}>Source</div>
                    <div style={valueStyle}>{detail.trusted_source_name}</div>
                  </div>
                )}
                {detail.trust_tier && (
                  <div>
                    <div style={labelStyle}>Trust Tier</div>
                    <div style={valueStyle}>{detail.trust_tier}</div>
                  </div>
                )}
                {detail.provenance_status && (
                  <div>
                    <div style={labelStyle}>Provenance</div>
                    <div style={valueStyle}>{detail.provenance_status}</div>
                  </div>
                )}
                {detail.content_type && (
                  <div>
                    <div style={labelStyle}>Content Type</div>
                    <div style={valueStyle}>{detail.content_type}</div>
                  </div>
                )}
              </div>

              {detail.dates && detail.dates.length > 0 && (
                <div style={{ marginBottom: '12px' }}>
                  <div style={{ ...labelStyle, marginBottom: '6px' }}>Dating</div>
                  {detail.dates.map((d, i) => (
                    <div key={i} style={{
                      display: 'flex', gap: '8px', padding: '6px 10px',
                      background: 'var(--bg-tertiary)', borderRadius: '6px',
                      border: '1px solid var(--border)', marginBottom: '4px',
                      fontSize: '11px', color: 'var(--text-primary)',
                    }}>
                      <span style={{ fontWeight: 600, minWidth: '60px' }}>{d.date_type}</span>
                      <span>{d.date_label || `${d.date_start ?? '?'} – ${d.date_end ?? '?'}`}</span>
                      <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: '10px' }}>
                        {d.dating_confidence}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {detail.text_excerpt && (
                <div style={{ marginBottom: '12px' }}>
                  <div style={{ ...labelStyle, marginBottom: '6px' }}>Source Text</div>
                  <div style={{
                    fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.6,
                    padding: '10px 12px', background: 'var(--bg-tertiary)', borderRadius: '8px',
                    border: '1px solid var(--border)', maxHeight: '200px', overflow: 'auto',
                    whiteSpace: 'pre-wrap',
                  }}>
                    {detail.text_excerpt}
                  </div>
                </div>
              )}

              {detail.source_url && (
                <a
                  href={detail.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    display: 'inline-block', fontSize: '10px', color: 'var(--accent)',
                    textDecoration: 'none', padding: '4px 8px', borderRadius: '4px',
                    border: '1px solid var(--border)', background: 'var(--bg-tertiary)',
                  }}
                >
                  View Original Source &rarr;
                </a>
              )}

              {detail.metadata && Object.keys(detail.metadata).length > 0 && (
                <MetadataSection metadata={detail.metadata} labelStyle={labelStyle} />
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function MetadataSection({ metadata, labelStyle }: { metadata: Record<string, unknown>; labelStyle: React.CSSProperties }) {
  const [expanded, setExpanded] = useState(false)
  const entries = Object.entries(metadata).filter(([, v]) => v != null && v !== '')

  if (entries.length === 0) return null

  return (
    <div style={{ marginTop: '12px' }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{ ...labelStyle, cursor: 'pointer', userSelect: 'none', marginBottom: '6px' }}
      >
        Metadata ({entries.length} fields) {expanded ? '▾' : '▸'}
      </div>
      {expanded && (
        <div style={{
          padding: '10px 12px', background: 'var(--bg-tertiary)', borderRadius: '8px',
          border: '1px solid var(--border)', maxHeight: '200px', overflow: 'auto',
        }}>
          {entries.map(([key, value]) => (
            <div key={key} style={{ marginBottom: '4px' }}>
              <span style={{ fontSize: '10px', fontWeight: 600, color: 'var(--text-muted)' }}>{key}: </span>
              <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                {typeof value === 'object' ? JSON.stringify(value) : String(value)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function EvidenceGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: '12px' }}>
      <div style={{
        fontSize: '10px',
        fontWeight: 600,
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        marginBottom: '6px',
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}

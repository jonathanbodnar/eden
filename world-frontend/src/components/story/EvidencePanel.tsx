import { useState, useEffect } from 'react'
import { api } from '../../api'
import type { StoryChapter, StoryEvidence, EntityMergeBreakdown, CultureVariant } from '../../api'

interface Props {
  chapter: StoryChapter | null
  evidence: StoryEvidence[]
  selectedEntity: { entityType: string; entityId: string; entityName: string } | null
  onClearEntity?: () => void
  activeCulture?: CultureVariant | null
}

function ScoreBar({ value, label, color }: { value: number; label: string; color?: string }) {
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>
        <span>{label}</span>
        <span>{(value * 100).toFixed(0)}%</span>
      </div>
      <div style={{ height: 4, background: 'var(--bg-secondary)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${value * 100}%`,
          background: color || 'var(--gold)',
          borderRadius: 2,
        }} />
      </div>
    </div>
  )
}

function CriterionBadge({ label, met }: { label: string; met: boolean | undefined }) {
  if (met === undefined) return null
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      padding: '2px 8px',
      fontSize: 11,
      borderRadius: 8,
      background: met ? 'rgba(168, 213, 162, 0.15)' : 'rgba(255,100,100,0.1)',
      border: `1px solid ${met ? 'rgba(168, 213, 162, 0.4)' : 'rgba(255,100,100,0.25)'}`,
      color: met ? '#a8d5a2' : '#ff8888',
    }}>
      {met ? '\u2713' : '\u2717'} {label}
    </span>
  )
}

function EntityBreakdownView({ data, onBack, archetypeName }: { data: EntityMergeBreakdown; onBack: () => void; archetypeName?: string }) {
  const displayName = archetypeName || data.entity.name
  const isArchetype = archetypeName && archetypeName !== data.entity.name
  return (
    <>
      <div style={{
        padding: '16px',
        borderBottom: '1px solid var(--border)',
      }}>
        <button
          onClick={onBack}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            fontSize: 11,
            padding: 0,
            marginBottom: 8,
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
        >
          &larr; Back to evidence
        </button>
        <div style={{
          fontSize: 11,
          textTransform: 'uppercase',
          letterSpacing: 1.5,
          color: 'var(--gold)',
          marginBottom: 4,
        }}>
          Entity Breakdown
        </div>
        <div style={{
          fontSize: 16,
          fontWeight: 700,
          color: 'var(--text-primary)',
          lineHeight: 1.3,
        }}>
          {displayName}
        </div>
        {isArchetype && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            Resolved as: {data.entity.name}
          </div>
        )}
        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
          {data.entity.subtype}
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        {/* Summary */}
        {data.entity.summary && (
          <div style={{
            fontSize: 13,
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
            marginBottom: 16,
            fontStyle: 'italic',
          }}>
            {data.entity.summary}
          </div>
        )}

        {/* Score */}
        {data.entity.score && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 1,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}>
              Confidence Score: {(data.entity.score.final * 100).toFixed(0)}%
            </div>
            <ScoreBar value={data.entity.score.age} label="Age Weight" />
            <ScoreBar value={data.entity.score.corroboration} label="Corroboration" />
            <ScoreBar value={data.entity.score.independence} label="Independence" />
            <ScoreBar value={data.entity.score.ambiguity} label="Ambiguity" color="#ff8888" />
          </div>
        )}

        {/* Cultures */}
        {data.cultures.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 1,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}>
              Found in {data.cultures.length} culture{data.cultures.length !== 1 ? 's' : ''}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {data.cultures.map(c => (
                <span key={c} style={{
                  padding: '3px 8px',
                  background: 'rgba(212, 168, 83, 0.12)',
                  border: '1px solid rgba(212, 168, 83, 0.3)',
                  borderRadius: 10,
                  fontSize: 11,
                  color: 'var(--gold)',
                }}>
                  {c}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Merged Equivalences */}
        {data.equivalences.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 1,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}>
              Merged Identities ({data.equivalences.length})
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, lineHeight: 1.5 }}>
              This entity was identified as equivalent to the following entities across cultures, based on Law 8 (Entity Convergence):
            </div>
            {data.equivalences.map((eq, i) => (
              <div key={i} style={{
                padding: '10px 12px',
                background: 'var(--bg-tertiary)',
                borderRadius: 8,
                marginBottom: 8,
                borderLeft: `3px solid ${eq.confidence >= 0.8 ? 'var(--gold)' : 'var(--border)'}`,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 4 }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-primary)' }}>
                    {eq.equivalent_name || eq.equivalent_id}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {(eq.confidence * 100).toFixed(0)}% confidence
                  </span>
                </div>
                {eq.equivalent_summary && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6, lineHeight: 1.5 }}>
                    {eq.equivalent_summary.slice(0, 200)}
                  </div>
                )}
                {eq.cultures.length > 0 && (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginBottom: 6 }}>
                    {eq.cultures.map(c => (
                      <span key={c} style={{
                        fontSize: 10,
                        padding: '1px 6px',
                        background: 'var(--bg-secondary)',
                        borderRadius: 6,
                        color: 'var(--text-muted)',
                      }}>
                        {c}
                      </span>
                    ))}
                  </div>
                )}
                {eq.reasoning && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 6, lineHeight: 1.5 }}>
                    <strong>Why merged:</strong> {eq.reasoning}
                  </div>
                )}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                  <CriterionBadge label="Role" met={eq.role_match} />
                  <CriterionBadge label="Action" met={eq.action_match} />
                  <CriterionBadge label="Context" met={eq.context_match} />
                  <CriterionBadge label="Pattern" met={eq.pattern_match} />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Source Evidence */}
        {data.sources.length > 0 && (
          <div>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 1,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}>
              Source Evidence ({data.sources.length})
            </div>
            {data.sources.map((src, i) => (
              <details key={i} style={{
                marginBottom: 6,
                background: 'var(--bg-tertiary)',
                borderRadius: 6,
                overflow: 'hidden',
              }}>
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
                  <span style={{ flex: 1, marginRight: 8 }}>{src.title}</span>
                  {src.culture && (
                    <span style={{
                      fontSize: 10,
                      padding: '2px 6px',
                      background: 'var(--bg-secondary)',
                      borderRadius: 8,
                      color: 'var(--text-muted)',
                      flexShrink: 0,
                    }}>
                      {src.culture}
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
                  {src.excerpt || 'No excerpt available'}
                </div>
              </details>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

function CultureEntitiesView({ culture }: { culture: CultureVariant }) {
  return (
    <>
      <div style={{ padding: '16px', borderBottom: '1px solid var(--border)' }}>
        <div style={{
          fontSize: 11, textTransform: 'uppercase', letterSpacing: 1.5,
          color: 'var(--gold)', marginBottom: 4,
        }}>
          {culture.culture} Tradition
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
          {culture.source_count} sources
          {culture.actors.length > 0 && ` \u00B7 ${culture.actors.length} figures`}
          {culture.events.length > 0 && ` \u00B7 ${culture.events.length} events`}
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        {culture.actors.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11, textTransform: 'uppercase', letterSpacing: 1,
              color: 'var(--gold)', marginBottom: 8,
            }}>
              Key Figures ({culture.actors.length})
            </div>
            {culture.actors.map(a => (
              <div key={a.id} style={{
                padding: '8px 10px', background: 'var(--bg-tertiary)',
                borderRadius: 6, marginBottom: 6,
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {a.name}
                </div>
                {a.summary && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5, marginTop: 2 }}>
                    {a.summary.slice(0, 200)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {culture.events.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11, textTransform: 'uppercase', letterSpacing: 1,
              color: '#7eb8da', marginBottom: 8,
            }}>
              Key Events ({culture.events.length})
            </div>
            {culture.events.map(e => (
              <div key={e.id} style={{
                padding: '8px 10px', background: 'var(--bg-tertiary)',
                borderRadius: 6, marginBottom: 6,
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {e.name}
                </div>
                {e.summary && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5, marginTop: 2 }}>
                    {e.summary.slice(0, 200)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {culture.places.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11, textTransform: 'uppercase', letterSpacing: 1,
              color: '#a8d5a2', marginBottom: 8,
            }}>
              Key Places ({culture.places.length})
            </div>
            {culture.places.map(p => (
              <div key={p.id} style={{
                padding: '8px 10px', background: 'var(--bg-tertiary)',
                borderRadius: 6, marginBottom: 6,
              }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
                  {p.name}
                </div>
                {p.summary && (
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5, marginTop: 2 }}>
                    {p.summary.slice(0, 200)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}

export default function EvidencePanel({ chapter, evidence, selectedEntity, onClearEntity, activeCulture }: Props) {
  const [mergeData, setMergeData] = useState<EntityMergeBreakdown | null>(null)
  const [loadingMerge, setLoadingMerge] = useState(false)

  useEffect(() => {
    if (!selectedEntity) {
      setMergeData(null)
      return
    }
    // Find also_known_as from the chapter's entity mentions
    const mention = chapter?.entity_mentions?.find(
      m => m.canonical_id === selectedEntity.entityId
    )
    const aka = mention?.also_known_as
    setLoadingMerge(true)
    api.getEntityMergeBreakdown(selectedEntity.entityType, selectedEntity.entityId, aka)
      .then(setMergeData)
      .catch(() => setMergeData(null))
      .finally(() => setLoadingMerge(false))
  }, [selectedEntity, chapter])

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

  if (loadingMerge) {
    return (
      <div style={{
        background: 'var(--bg-secondary)',
        borderLeft: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--text-muted)',
      }}>
        Loading entity breakdown...
      </div>
    )
  }

  if (activeCulture && !selectedEntity) {
    return (
      <div style={{
        background: 'var(--bg-secondary)',
        borderLeft: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}>
        <CultureEntitiesView culture={activeCulture} />
      </div>
    )
  }

  if (mergeData && selectedEntity) {
    return (
      <div style={{
        background: 'var(--bg-secondary)',
        borderLeft: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}>
        <EntityBreakdownView
          data={mergeData}
          onBack={() => onClearEntity?.()}
          archetypeName={selectedEntity?.entityName}
        />
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
        {chapter.time_hint && (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            {chapter.time_hint}
          </div>
        )}
        {chapter.themes && chapter.themes.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
            {chapter.themes.map((t, i) => (
              <span key={i} style={{
                fontSize: 10,
                padding: '2px 6px',
                background: 'rgba(212, 168, 83, 0.1)',
                border: '1px solid rgba(212, 168, 83, 0.25)',
                borderRadius: 8,
                color: 'var(--gold)',
              }}>
                {t}
              </span>
            ))}
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
        {/* Entity Mentions Quick List */}
        {chapter.entity_mentions && chapter.entity_mentions.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 11,
              textTransform: 'uppercase',
              letterSpacing: 1,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}>
              Entities in this Chapter
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {chapter.entity_mentions.map((m, i) => (
                <button
                  key={i}
                  disabled={!m.canonical_id}
                  onClick={() => m.canonical_id && onClearEntity
                    ? (() => {
                        const evt = new CustomEvent('entity-click', { detail: { entityType: m.type, entityId: m.canonical_id, entityName: m.name } })
                        window.dispatchEvent(evt)
                      })()
                    : undefined
                  }
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 10px',
                    background: 'var(--bg-tertiary)',
                    border: 'none',
                    borderRadius: 6,
                    cursor: m.canonical_id ? 'pointer' : 'default',
                    textAlign: 'left',
                    width: '100%',
                  }}
                >
                  <span style={{
                    fontSize: 10,
                    padding: '1px 5px',
                    borderRadius: 4,
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    color: m.type === 'actor' ? 'var(--gold)' : m.type === 'event' ? '#7eb8da' : '#a8d5a2',
                    background: m.type === 'actor' ? 'rgba(212,168,83,0.1)' : m.type === 'event' ? 'rgba(126,184,218,0.1)' : 'rgba(168,213,162,0.1)',
                  }}>
                    {m.type}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-primary)', fontWeight: 500 }}>
                    {m.name}
                  </span>
                  {m.also_known_as && m.also_known_as.length > 0 && (
                    <span style={{ fontSize: 10, color: 'var(--text-muted)', flex: 1, textAlign: 'right' }}>
                      +{m.also_known_as.length} names
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

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

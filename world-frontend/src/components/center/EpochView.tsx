import { useWorldContext } from '../../context/WorldContext'
import type { CultureSummary } from '../../api'

function formatYear(y: number | null): string {
  if (y === null) return '?'
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

const CULTURE_ICONS: Record<string, string> = {
  Sumerian: '\u{1F3DB}',
  Akkadian: '\u{2694}',
  Babylonian: '\u{1F3DB}',
  Egyptian: '\u{1F3FA}',
  Hittite: '\u{1F6E1}',
  Assyrian: '\u{1F981}',
  Elamite: '\u{1F3FA}',
  Persian: '\u{1F451}',
  Greek: '\u{1F3DB}',
  Roman: '\u{1F3DB}',
  Ugaritic: '\u{1F4DC}',
  Indic: '\u{1F549}',
  Chinese: '\u{1F409}',
  Celtic: '\u{2618}',
  Norse: '\u{2694}',
  Phoenician: '\u{26F5}',
  Mesoamerican: '\u{1F332}',
  General: '\u{1F30D}',
  Mesopotamian: '\u{1F3DB}',
}

function getCultureIcon(name: string): string {
  for (const [key, icon] of Object.entries(CULTURE_ICONS)) {
    if (name.toLowerCase().includes(key.toLowerCase())) return icon
  }
  return '\u{1F30D}'
}

function CultureCard({ culture, onClick }: { culture: CultureSummary; onClick: () => void }) {
  const total = culture.source_count + culture.actor_count + culture.event_count + culture.place_count
  const icon = getCultureIcon(culture.name)

  return (
    <button
      onClick={onClick}
      disabled={!culture.explorable}
      style={{
        background: culture.explorable
          ? 'linear-gradient(135deg, var(--bg-tertiary), var(--bg-secondary))'
          : 'var(--bg-tertiary)',
        border: '1px solid var(--border)',
        borderRadius: '10px',
        padding: '16px',
        cursor: culture.explorable ? 'pointer' : 'default',
        textAlign: 'left',
        transition: 'all 0.2s',
        opacity: culture.explorable ? 1 : 0.5,
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        minWidth: 0,
      }}
      onMouseEnter={e => {
        if (culture.explorable) {
          (e.currentTarget as HTMLElement).style.borderColor = 'var(--accent)'
          ;(e.currentTarget as HTMLElement).style.transform = 'translateY(-2px)'
        }
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'
        ;(e.currentTarget as HTMLElement).style.transform = 'translateY(0)'
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '20px' }}>{icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--text-primary)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {culture.name}
          </div>
        </div>
        {culture.explorable && (
          <span style={{
            fontSize: '10px',
            color: 'var(--accent)',
            padding: '2px 6px',
            borderRadius: '4px',
            background: 'var(--accent-dim)',
            fontWeight: 600,
          }}>
            Explore
          </span>
        )}
      </div>

      <div style={{
        display: 'flex',
        gap: '10px',
        flexWrap: 'wrap',
        fontSize: '10px',
        color: 'var(--text-muted)',
      }}>
        {culture.source_count > 0 && (
          <span>{culture.source_count} source{culture.source_count !== 1 ? 's' : ''}</span>
        )}
        {culture.actor_count > 0 && (
          <span>{culture.actor_count} actor{culture.actor_count !== 1 ? 's' : ''}</span>
        )}
        {culture.event_count > 0 && (
          <span>{culture.event_count} event{culture.event_count !== 1 ? 's' : ''}</span>
        )}
        {culture.place_count > 0 && (
          <span>{culture.place_count} place{culture.place_count !== 1 ? 's' : ''}</span>
        )}
        {total === 0 && <span>No data yet</span>}
      </div>
    </button>
  )
}

function ChapterTimeline({ chapters, epoch, onSelectChapter }: {
  chapters: { id: string; title: string; time_start: number | null; time_end: number | null }[]
  epoch: { time_start: number | null; time_end: number | null }
  onSelectChapter: (id: string) => void
}) {
  const dated = chapters.filter(c => c.time_start !== null && c.time_end !== null)
  if (dated.length === 0 || !epoch.time_start || !epoch.time_end) return null

  const span = epoch.time_end - epoch.time_start || 1
  const slices = new Map<string, { start: number; end: number; count: number; title: string; id: string }>()

  for (const ch of dated) {
    const key = `${ch.time_start}-${ch.time_end}`
    if (!slices.has(key)) {
      slices.set(key, { start: ch.time_start!, end: ch.time_end!, count: 0, title: ch.title, id: ch.id })
    }
    slices.get(key)!.count++
  }

  const maxCount = Math.max(...Array.from(slices.values()).map(s => s.count))

  return (
    <div style={{ marginBottom: '20px', animation: 'slideUp 0.3s' }}>
      <h2 style={{
        fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '8px',
      }}>
        Chapter Distribution ({dated.length} dated chapters)
      </h2>
      <div style={{
        position: 'relative', height: '48px', background: 'var(--bg-tertiary)',
        borderRadius: '8px', border: '1px solid var(--border)', overflow: 'hidden',
      }}>
        {Array.from(slices.values()).map((s, i) => {
          const left = ((s.start - epoch.time_start!) / span) * 100
          const width = Math.max(((s.end - s.start) / span) * 100, 1)
          const opacity = 0.3 + (s.count / maxCount) * 0.7
          return (
            <div
              key={i}
              onClick={() => onSelectChapter(s.id)}
              title={`${s.title} (${s.count} chapter${s.count > 1 ? 's' : ''})`}
              style={{
                position: 'absolute', left: `${left}%`, width: `${width}%`,
                top: '4px', bottom: '4px', background: `rgba(99, 102, 241, ${opacity})`,
                borderRadius: '3px', cursor: 'pointer', transition: 'background 0.15s',
                minWidth: '3px',
              }}
            />
          )
        })}
        <div style={{
          position: 'absolute', bottom: '2px', left: '8px',
          fontSize: '9px', color: 'var(--text-muted)',
        }}>
          {formatYear(epoch.time_start)}
        </div>
        <div style={{
          position: 'absolute', bottom: '2px', right: '8px',
          fontSize: '9px', color: 'var(--text-muted)',
        }}>
          {formatYear(epoch.time_end)}
        </div>
      </div>
    </div>
  )
}

export default function EpochView() {
  const { epochOverview, selectCulture, selectChapter } = useWorldContext()
  if (!epochOverview) return null

  const { epoch, cultures, total_sources, total_actors, total_events, total_places, chapters } = epochOverview
  const explorableCultures = cultures.filter(c => c.explorable)
  const otherCultures = cultures.filter(c => !c.explorable)

  return (
    <div style={{
      height: '100%',
      overflow: 'hidden',
      display: 'flex',
      flexDirection: 'column',
      background: `
        radial-gradient(ellipse at 30% 20%, rgba(212, 168, 83, 0.06) 0%, transparent 50%),
        radial-gradient(ellipse at 70% 80%, rgba(99, 102, 241, 0.04) 0%, transparent 50%),
        var(--bg-primary)
      `,
    }}>
      <div style={{
        padding: '24px 32px 16px',
        flexShrink: 0,
        borderBottom: '1px solid var(--border)',
        animation: 'fadeIn 0.3s',
      }}>
        <div style={{
          fontSize: '10px',
          color: 'var(--gold)',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          marginBottom: '4px',
        }}>
          {formatYear(epoch.time_start)} — {formatYear(epoch.time_end)}
        </div>
        <h1 style={{
          fontSize: '22px',
          fontWeight: 700,
          color: 'var(--text-primary)',
          marginBottom: '8px',
        }}>
          {epoch.title}
        </h1>

        <div style={{
          display: 'flex',
          gap: '16px',
          flexWrap: 'wrap',
          fontSize: '11px',
          color: 'var(--text-muted)',
        }}>
          {total_sources > 0 && <span>{total_sources} sources consulted</span>}
          {total_actors > 0 && <span>{total_actors} actors identified</span>}
          {total_events > 0 && <span>{total_events} events recorded</span>}
          {total_places > 0 && <span>{total_places} places mapped</span>}
          {cultures.length > 0 && (
            <span style={{ color: 'var(--accent)' }}>
              {cultures.length} culture{cultures.length !== 1 ? 's' : ''} represented
            </span>
          )}
        </div>

        {epoch.summary && (
          <p style={{
            marginTop: '10px',
            fontSize: '12px',
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
            maxWidth: '700px',
          }}>
            {epoch.summary}
          </p>
        )}
      </div>

      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '20px 32px 32px',
      }}>
        {chapters && (
          <ChapterTimeline
            chapters={chapters}
            epoch={epoch}
            onSelectChapter={selectChapter}
          />
        )}

        {explorableCultures.length > 0 && (
          <div style={{ marginBottom: '24px', animation: 'slideUp 0.4s' }}>
            <h2 style={{
              fontSize: '11px',
              fontWeight: 600,
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: '12px',
            }}>
              Explorable Civilizations
            </h2>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: '10px',
            }}>
              {explorableCultures.map(c => (
                <CultureCard
                  key={c.name}
                  culture={c}
                  onClick={() => selectCulture(c.name)}
                />
              ))}
            </div>
          </div>
        )}

        {otherCultures.length > 0 && (
          <div style={{ animation: 'slideUp 0.5s' }}>
            <h2 style={{
              fontSize: '11px',
              fontWeight: 600,
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              marginBottom: '10px',
            }}>
              Other Cultures Referenced
            </h2>
            <div style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '6px',
            }}>
              {otherCultures.map(c => (
                <span
                  key={c.name}
                  style={{
                    fontSize: '10px',
                    padding: '4px 10px',
                    borderRadius: '12px',
                    border: '1px solid var(--border)',
                    color: 'var(--text-muted)',
                    background: 'var(--bg-tertiary)',
                  }}
                >
                  {getCultureIcon(c.name)} {c.name}
                  {c.source_count > 0 && ` · ${c.source_count}`}
                </span>
              ))}
            </div>
          </div>
        )}

        {chapters && chapters.length > 0 && (
          <div style={{ marginBottom: '24px', animation: 'slideUp 0.5s' }}>
            <h2 style={{
              fontSize: '11px', fontWeight: 600, color: 'var(--text-muted)',
              textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '10px',
            }}>
              Chapters ({chapters.length})
            </h2>
            <div style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
              gap: '8px',
              maxHeight: '400px',
              overflowY: 'auto',
            }}>
              {chapters.slice(0, 60).map(ch => (
                <button
                  key={ch.id}
                  onClick={() => selectChapter(ch.id)}
                  style={{
                    background: 'var(--bg-tertiary)',
                    border: '1px solid var(--border)',
                    borderRadius: '8px',
                    padding: '10px 12px',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'border-color 0.15s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent)')}
                  onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
                >
                  <div style={{
                    fontSize: '12px', fontWeight: 600, color: 'var(--text-primary)',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>
                    {ch.title}
                  </div>
                  {(ch.time_start !== null || ch.time_end !== null) && (
                    <div style={{ fontSize: '10px', color: 'var(--gold)', marginTop: '2px' }}>
                      {formatYear(ch.time_start)} — {formatYear(ch.time_end)}
                    </div>
                  )}
                </button>
              ))}
            </div>
            {chapters.length > 60 && (
              <div style={{
                textAlign: 'center', marginTop: '8px',
                fontSize: '10px', color: 'var(--text-muted)',
              }}>
                Showing 60 of {chapters.length} chapters. Use the left panel to browse all.
              </div>
            )}
          </div>
        )}

        {cultures.length === 0 && (!chapters || chapters.length === 0) && (
          <div style={{
            textAlign: 'center',
            padding: '40px 20px',
            color: 'var(--text-muted)',
            fontSize: '12px',
            animation: 'fadeIn 0.4s',
          }}>
            <p>No cultural data available yet for this epoch.</p>
            <p style={{ marginTop: '4px', fontSize: '11px' }}>
              As more sources are ingested and processed, cultures and entities will appear here.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

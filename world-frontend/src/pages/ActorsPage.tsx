import { useEffect, useMemo, useState } from 'react'

interface ActorEntry {
  name: string
  event_count: number
  cultures: string[]
  chapters: number[]
  verb_families: string[]
  top_outcomes: string[]
  match_score: number | null
}

interface ArchetypeEntry {
  archetype_id: string
  archetype_name: string
  entity_type: string | null
  role_description: string | null
  actor_count: number
  total_event_count: number
  cohesion_score: number | null
  actors: ActorEntry[]
}

type SortMode = 'cohesion_asc' | 'cohesion_desc' | 'size_desc' | 'name'
type FilterMode = 'all' | 'multi' | 'problems'

function colorForScore(s: number | null): string {
  if (s === null) return '#888'
  if (s >= 70) return '#4ade80'
  if (s >= 45) return '#facc15'
  if (s >= 20) return '#fb923c'
  return '#f87171'
}

function MiniMindMap({ arch }: { arch: ArchetypeEntry }) {
  const size = 340
  const cx = size / 2
  const cy = size / 2
  const centerR = 52
  const actorR = 26

  const actors = arch.actors
  const n = actors.length

  // Place actors on a circle around the center
  const radius = n <= 4 ? 100 : n <= 8 ? 120 : 135

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ display: 'block' }}
    >
      {/* Connection lines */}
      {actors.map((a, i) => {
        const angle = (i / Math.max(n, 1)) * Math.PI * 2 - Math.PI / 2
        const x = cx + Math.cos(angle) * radius
        const y = cy + Math.sin(angle) * radius
        const color = colorForScore(a.match_score)
        const strokeWidth =
          a.match_score === null ? 1 : 0.5 + (a.match_score / 100) * 2.5
        return (
          <line
            key={`line-${i}`}
            x1={cx}
            y1={cy}
            x2={x}
            y2={y}
            stroke={color}
            strokeWidth={strokeWidth}
            opacity={0.6}
          />
        )
      })}

      {/* Center archetype */}
      <circle
        cx={cx}
        cy={cy}
        r={centerR}
        fill="var(--bg-tertiary)"
        stroke="var(--gold)"
        strokeWidth={2}
      />
      <text
        x={cx}
        y={cy - 4}
        textAnchor="middle"
        fill="var(--gold)"
        fontSize={11}
        fontWeight={700}
      >
        {arch.archetype_name.split(' ').slice(0, 2).join(' ')}
      </text>
      <text
        x={cx}
        y={cy + 10}
        textAnchor="middle"
        fill="var(--gold)"
        fontSize={11}
        fontWeight={700}
      >
        {arch.archetype_name.split(' ').slice(2).join(' ')}
      </text>
      {arch.cohesion_score !== null && (
        <text
          x={cx}
          y={cy + 28}
          textAnchor="middle"
          fill={colorForScore(arch.cohesion_score)}
          fontSize={10}
          fontWeight={600}
        >
          {arch.cohesion_score}%
        </text>
      )}

      {/* Satellite actors */}
      {actors.map((a, i) => {
        const angle = (i / Math.max(n, 1)) * Math.PI * 2 - Math.PI / 2
        const x = cx + Math.cos(angle) * radius
        const y = cy + Math.sin(angle) * radius
        const color = colorForScore(a.match_score)
        const r = Math.min(actorR, Math.max(14, 14 + a.event_count * 1.5))
        // Position label outside the node
        const labelOffset = r + 10
        const lx = cx + Math.cos(angle) * (radius + labelOffset)
        const ly = cy + Math.sin(angle) * (radius + labelOffset)
        const textAnchor =
          Math.abs(Math.cos(angle)) < 0.3
            ? 'middle'
            : Math.cos(angle) > 0
              ? 'start'
              : 'end'
        return (
          <g key={`actor-${i}`}>
            <circle
              cx={x}
              cy={y}
              r={r}
              fill="var(--bg-primary)"
              stroke={color}
              strokeWidth={2}
            />
            {a.match_score !== null && (
              <text
                x={x}
                y={y + 3}
                textAnchor="middle"
                fill={color}
                fontSize={9}
                fontWeight={700}
              >
                {Math.round(a.match_score)}%
              </text>
            )}
            {a.match_score === null && (
              <text
                x={x}
                y={y + 3}
                textAnchor="middle"
                fill="var(--text-secondary)"
                fontSize={9}
              >
                solo
              </text>
            )}
            <text
              x={lx}
              y={ly}
              textAnchor={textAnchor}
              dominantBaseline="middle"
              fill="var(--text-primary)"
              fontSize={10}
            >
              {a.name.length > 18 ? a.name.slice(0, 17) + '…' : a.name}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function ActorDetail({ actor }: { actor: ActorEntry }) {
  return (
    <div
      style={{
        background: 'var(--bg-primary)',
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: 10,
        fontSize: 12,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 6,
        }}
      >
        <strong style={{ color: 'var(--text-primary)' }}>{actor.name}</strong>
        <span
          style={{
            color: colorForScore(actor.match_score),
            fontWeight: 600,
            fontSize: 11,
          }}
        >
          {actor.match_score === null ? 'solo' : `${actor.match_score}% match`}
        </span>
      </div>
      <div style={{ color: 'var(--text-secondary)', marginBottom: 4 }}>
        {actor.event_count} event{actor.event_count !== 1 ? 's' : ''}
        {' · '}
        {actor.cultures.length} culture
        {actor.cultures.length !== 1 ? 's' : ''}
        {actor.chapters.length > 0 && ` · ch ${actor.chapters.join(', ')}`}
      </div>
      {actor.verb_families.length > 0 && (
        <div
          style={{
            display: 'flex',
            gap: 4,
            flexWrap: 'wrap',
            marginBottom: 4,
          }}
        >
          {actor.verb_families.map(vf => (
            <span
              key={vf}
              style={{
                fontSize: 10,
                padding: '1px 6px',
                background: 'var(--bg-tertiary)',
                color: 'var(--text-secondary)',
                borderRadius: 3,
              }}
            >
              {vf}
            </span>
          ))}
        </div>
      )}
      {actor.top_outcomes.length > 0 && (
        <div
          style={{
            fontStyle: 'italic',
            color: 'var(--text-secondary)',
            fontSize: 11,
            lineHeight: 1.35,
          }}
        >
          {actor.top_outcomes.map((o, i) => (
            <div key={i}>• {o}</div>
          ))}
        </div>
      )}
    </div>
  )
}

function ArchetypeCard({ arch }: { arch: ArchetypeEntry }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div
      style={{
        background: 'var(--bg-secondary)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '10px 14px',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div>
          <div
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: 'var(--gold)',
            }}
          >
            {arch.archetype_name}
          </div>
          {arch.role_description && (
            <div
              style={{
                fontSize: 11,
                color: 'var(--text-secondary)',
                marginTop: 2,
                fontStyle: 'italic',
                maxWidth: 480,
              }}
            >
              {arch.role_description}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 10, color: 'var(--text-secondary)' }}>
              {arch.actor_count} actor{arch.actor_count !== 1 ? 's' : ''} ·{' '}
              {arch.total_event_count} evt
            </div>
            {arch.cohesion_score !== null && (
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: colorForScore(arch.cohesion_score),
                }}
              >
                {arch.cohesion_score}% cohesion
              </div>
            )}
          </div>
          <button
            onClick={() => setExpanded(e => !e)}
            style={{
              padding: '4px 10px',
              fontSize: 11,
              background: 'var(--bg-tertiary)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              color: 'var(--text-primary)',
              cursor: 'pointer',
            }}
          >
            {expanded ? 'Hide detail' : 'Detail'}
          </button>
        </div>
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: expanded ? '360px 1fr' : '1fr',
          gap: 14,
          padding: 12,
          background: 'var(--bg-primary)',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <MiniMindMap arch={arch} />
        </div>
        {expanded && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
              gap: 8,
              maxHeight: 340,
              overflowY: 'auto',
            }}
          >
            {arch.actors.map(a => (
              <ActorDetail key={a.name} actor={a} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function ActorsPage() {
  const [data, setData] = useState<ArchetypeEntry[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<SortMode>('cohesion_asc')
  const [filter, setFilter] = useState<FilterMode>('multi')

  useEffect(() => {
    fetch('/world-api/story/archetype-analysis')
      .then(r => {
        if (!r.ok) throw new Error(`${r.status}`)
        return r.json()
      })
      .then(setData)
      .catch(e => setErr(String(e)))
  }, [])

  const filtered = useMemo(() => {
    if (!data) return []
    let items = [...data]
    if (filter === 'multi') {
      items = items.filter(a => a.actor_count >= 2)
    } else if (filter === 'problems') {
      items = items.filter(
        a => a.cohesion_score !== null && a.cohesion_score < 45
      )
    }
    if (q.trim()) {
      const needle = q.trim().toLowerCase()
      items = items.filter(
        a =>
          a.archetype_name.toLowerCase().includes(needle) ||
          a.actors.some(ac => ac.name.toLowerCase().includes(needle)) ||
          (a.role_description || '').toLowerCase().includes(needle)
      )
    }
    if (sort === 'cohesion_asc') {
      items.sort((a, b) => {
        const va = a.cohesion_score ?? 999
        const vb = b.cohesion_score ?? 999
        return va - vb
      })
    } else if (sort === 'cohesion_desc') {
      items.sort((a, b) => {
        const va = a.cohesion_score ?? -1
        const vb = b.cohesion_score ?? -1
        return vb - va
      })
    } else if (sort === 'size_desc') {
      items.sort((a, b) => b.actor_count - a.actor_count)
    } else {
      items.sort((a, b) => a.archetype_name.localeCompare(b.archetype_name))
    }
    return items
  }, [data, q, sort, filter])

  const globalStats = useMemo(() => {
    if (!data) return null
    const total = data.length
    const multi = data.filter(a => a.actor_count >= 2).length
    const problems = data.filter(
      a => a.cohesion_score !== null && a.cohesion_score < 45
    ).length
    const solo = data.filter(a => a.actor_count === 1).length
    const avgCohesion = (() => {
      const vals = data
        .map(a => a.cohesion_score)
        .filter((v): v is number => v !== null)
      if (vals.length === 0) return null
      return Math.round(vals.reduce((s, v) => s + v, 0) / vals.length)
    })()
    return { total, multi, problems, solo, avgCohesion }
  }, [data])

  return (
    <div
      style={{
        height: '100%',
        overflowY: 'auto',
        background: 'var(--bg-primary)',
        color: 'var(--text-primary)',
      }}
    >
      <div
        style={{
          padding: '16px 24px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-secondary)',
          position: 'sticky',
          top: 0,
          zIndex: 10,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 10,
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: 18 }}>Actor Archetypes</h2>
            <div
              style={{
                fontSize: 12,
                color: 'var(--text-secondary)',
                marginTop: 2,
                maxWidth: 720,
              }}
            >
              Each archetype is a role the unified narrative uses to describe
              several culture-specific actors. The % match shows how well an
              actor's verb/outcome footprint aligns with the others in the
              same archetype. Low cohesion = likely over-merging.
            </div>
          </div>
          {globalStats && (
            <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
              <div>
                <strong>{globalStats.total}</strong> archetypes ·{' '}
                <strong>{globalStats.multi}</strong> multi-actor ·{' '}
                <strong style={{ color: '#f87171' }}>
                  {globalStats.problems}
                </strong>{' '}
                low cohesion
              </div>
              {globalStats.avgCohesion !== null && (
                <div style={{ textAlign: 'right' }}>
                  avg cohesion:{' '}
                  <strong
                    style={{
                      color: colorForScore(globalStats.avgCohesion),
                    }}
                  >
                    {globalStats.avgCohesion}%
                  </strong>
                </div>
              )}
            </div>
          )}
        </div>
        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            flexWrap: 'wrap',
          }}
        >
          <input
            type="text"
            placeholder="Search archetype or actor…"
            value={q}
            onChange={e => setQ(e.target.value)}
            style={{
              flex: '1 1 280px',
              maxWidth: 420,
              padding: '6px 10px',
              fontSize: 12,
              background: 'var(--bg-primary)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              color: 'var(--text-primary)',
            }}
          />
          <select
            value={filter}
            onChange={e => setFilter(e.target.value as FilterMode)}
            style={{
              padding: '6px 8px',
              fontSize: 12,
              background: 'var(--bg-primary)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              color: 'var(--text-primary)',
            }}
          >
            <option value="all">All archetypes</option>
            <option value="multi">Multi-actor only</option>
            <option value="problems">Low cohesion (under 45%)</option>
          </select>
          <select
            value={sort}
            onChange={e => setSort(e.target.value as SortMode)}
            style={{
              padding: '6px 8px',
              fontSize: 12,
              background: 'var(--bg-primary)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              color: 'var(--text-primary)',
            }}
          >
            <option value="cohesion_asc">Cohesion (low → high)</option>
            <option value="cohesion_desc">Cohesion (high → low)</option>
            <option value="size_desc">Actor count</option>
            <option value="name">Alphabetical</option>
          </select>
        </div>
      </div>

      <div style={{ padding: '16px 24px' }}>
        {err && (
          <div style={{ color: '#f87171', padding: 12 }}>Error: {err}</div>
        )}
        {!data && !err && (
          <div style={{ color: 'var(--text-secondary)', padding: 12 }}>
            Loading archetype analysis…
          </div>
        )}
        {data && filtered.length === 0 && (
          <div style={{ color: 'var(--text-secondary)', padding: 12 }}>
            No archetypes match the current filter.
          </div>
        )}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(520px, 1fr))',
            gap: 14,
          }}
        >
          {filtered.map(a => (
            <ArchetypeCard key={a.archetype_id} arch={a} />
          ))}
        </div>
      </div>
    </div>
  )
}

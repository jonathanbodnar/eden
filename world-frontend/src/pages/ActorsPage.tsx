import { useEffect, useMemo, useState } from 'react'
import type { CSSProperties } from 'react'

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

interface DossierAction {
  verb?: string
  verb_family?: string
  outcome?: string
  objects?: string[]
  culture_key?: string
  chapter_number?: number
  source_ref?: string
  quoted_phrase?: string
}

interface PassageExcerpt {
  source_id: string
  title: string
  culture: string | null
  excerpt: string
}

interface DeityDossier {
  id: string
  actor_name: string
  normalized_name: string
  canonical_actor_id: string | null
  cultures: string[]
  event_count: number
  actions: DossierAction[]
  co_occurring_actors: Record<string, number>
  earliest_source_id: string | null
  earliest_source_title: string | null
  earliest_date_start: number | null
  earliest_date_end: number | null
  earliest_date_label: string | null
  dating_confidence: string | null
  source_passage_excerpts: PassageExcerpt[]
  characteristics_md: string | null
  current_archetype_id: string | null
  current_archetype_name: string | null
  updated_at: string | null
}

interface ProposalGroup {
  proposed_archetype_name: string
  role_description: string
  members: string[]
  rationale: string
  evidence: string[]
}

interface ArchetypeMergeProposal {
  id: string
  epoch_id: string
  source_archetype_ids: string[]
  source_archetype_names: string[]
  proposal_kind: 'keep' | 'split' | 'reassign' | 'merge'
  proposed_groups: ProposalGroup[]
  overall_rationale: string | null
  confidence: number | null
  status: 'pending' | 'approved' | 'rejected' | 'applied'
  applied_at: string | null
  applied_note: string | null
  model_name: string | null
  created_at: string | null
  updated_at: string | null
}

type SortMode = 'cohesion_asc' | 'cohesion_desc' | 'size_desc' | 'events_desc' | 'name'
type FilterMode = 'all' | 'multi' | 'problems' | 'with_events'
type CardTab = 'map' | 'dossiers' | 'proposal'

function normalizeName(s: string): string {
  return (s || '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

const toolbarBtnStyle: CSSProperties = {
  padding: '6px 12px',
  fontSize: 11,
  background: 'var(--bg-primary)',
  border: '1px solid var(--border)',
  borderRadius: 4,
  color: 'var(--text-primary)',
  cursor: 'pointer',
  whiteSpace: 'nowrap',
}

function formatDate(start: number | null, end: number | null, label: string | null): string {
  if (start == null && end == null) return label || '—'
  const fmt = (v: number) => {
    if (v < 0) return `${Math.abs(v).toLocaleString()} BCE`
    return `${v.toLocaleString()} CE`
  }
  if (start != null && end != null && start !== end) return `${fmt(start)} – ${fmt(end)}`
  if (start != null) return fmt(start)
  if (end != null) return fmt(end)
  return label || '—'
}

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

function DossierPanel({ dossier }: { dossier: DeityDossier | null }) {
  if (!dossier) {
    return (
      <div style={{ fontSize: 11, color: 'var(--text-secondary)', padding: 8 }}>
        No dossier built yet. Run <code>POST /admin/build-deity-dossiers?epoch_orders=0</code>.
      </div>
    )
  }
  const topCooc = Object.entries(dossier.co_occurring_actors)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)

  return (
    <div
      style={{
        background: 'var(--bg-primary)',
        border: '1px solid var(--border)',
        borderRadius: 6,
        padding: 10,
        marginBottom: 8,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontWeight: 700, color: 'var(--gold)', fontSize: 13 }}>
          {dossier.actor_name}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-secondary)' }}>
          {dossier.event_count} event{dossier.event_count !== 1 ? 's' : ''} ·{' '}
          {dossier.cultures.length} culture{dossier.cultures.length !== 1 ? 's' : ''}
        </div>
      </div>

      {dossier.earliest_source_title && (
        <div style={{ fontSize: 11, marginTop: 4, color: 'var(--text-secondary)' }}>
          <strong>Earliest attestation:</strong> {dossier.earliest_source_title} (
          {formatDate(dossier.earliest_date_start, dossier.earliest_date_end, dossier.earliest_date_label)}
          )
          {dossier.dating_confidence ? ` · ${dossier.dating_confidence}` : ''}
        </div>
      )}

      {dossier.cultures.length > 0 && (
        <div style={{ fontSize: 11, marginTop: 3, color: 'var(--text-secondary)' }}>
          <strong>Cultures:</strong> {dossier.cultures.join(', ')}
        </div>
      )}

      {topCooc.length > 0 && (
        <div style={{ fontSize: 11, marginTop: 3, color: 'var(--text-secondary)' }}>
          <strong>Co-occurs with:</strong>{' '}
          {topCooc.map(([n, c]) => `${n} (${c})`).join(', ')}
        </div>
      )}

      {dossier.actions.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ cursor: 'pointer', fontSize: 11 }}>
            Actions ({dossier.actions.length})
          </summary>
          <div style={{ maxHeight: 140, overflowY: 'auto', marginTop: 4 }}>
            {dossier.actions.slice(0, 20).map((a, i) => (
              <div key={i} style={{ fontSize: 10, marginBottom: 3, fontFamily: 'monospace' }}>
                <span style={{ color: 'var(--text-secondary)' }}>[{a.culture_key}]</span>{' '}
                <span style={{ color: '#a78bfa' }}>{a.verb}</span> → {a.outcome}
              </div>
            ))}
          </div>
        </details>
      )}

      {dossier.characteristics_md && (
        <div
          style={{
            marginTop: 8,
            padding: 8,
            background: 'var(--bg-secondary)',
            borderRadius: 4,
            fontSize: 11.5,
            lineHeight: 1.5,
            whiteSpace: 'pre-wrap',
          }}
        >
          {dossier.characteristics_md}
        </div>
      )}

      {dossier.source_passage_excerpts.length > 0 && (
        <details style={{ marginTop: 6 }}>
          <summary style={{ cursor: 'pointer', fontSize: 11 }}>
            Source passages ({dossier.source_passage_excerpts.length})
          </summary>
          <div style={{ maxHeight: 200, overflowY: 'auto', marginTop: 4 }}>
            {dossier.source_passage_excerpts.map((p, i) => (
              <div
                key={i}
                style={{
                  fontSize: 10.5,
                  marginBottom: 8,
                  padding: 6,
                  background: 'var(--bg-tertiary)',
                  borderRadius: 4,
                }}
              >
                <div style={{ fontWeight: 600, marginBottom: 2 }}>
                  {p.title} {p.culture ? `· ${p.culture}` : ''}
                </div>
                <div style={{ fontStyle: 'italic', color: 'var(--text-secondary)' }}>
                  {(p.excerpt || '').slice(0, 500)}
                  {(p.excerpt || '').length > 500 ? '…' : ''}
                </div>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

function ProposalPanel({
  proposal,
  onApprove,
  onReject,
  working,
}: {
  proposal: ArchetypeMergeProposal | null
  onApprove: () => void
  onReject: () => void
  working: boolean
}) {
  if (!proposal) {
    return (
      <div style={{ fontSize: 11, color: 'var(--text-secondary)', padding: 8 }}>
        No proposal generated yet. Run{' '}
        <code>POST /admin/propose-archetype-remerges?epoch_orders=0</code>.
      </div>
    )
  }
  const isActionable = proposal.status === 'pending'
  const verdictColor =
    proposal.proposal_kind === 'keep'
      ? '#4ade80'
      : proposal.proposal_kind === 'split' || proposal.proposal_kind === 'reassign'
      ? '#facc15'
      : '#a78bfa'
  return (
    <div style={{ padding: 4 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          marginBottom: 8,
        }}
      >
        <div>
          <span
            style={{
              display: 'inline-block',
              padding: '2px 8px',
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 700,
              background: 'var(--bg-tertiary)',
              color: verdictColor,
              textTransform: 'uppercase',
              marginRight: 8,
            }}
          >
            {proposal.proposal_kind}
          </span>
          {proposal.confidence != null && (
            <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
              confidence {Math.round((proposal.confidence || 0) * 100)}%
            </span>
          )}
          {proposal.model_name && (
            <span style={{ fontSize: 10, color: 'var(--text-secondary)', marginLeft: 8 }}>
              ({proposal.model_name})
            </span>
          )}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
          status:{' '}
          <strong
            style={{
              color:
                proposal.status === 'applied'
                  ? '#4ade80'
                  : proposal.status === 'rejected'
                  ? '#f87171'
                  : 'var(--text-primary)',
            }}
          >
            {proposal.status}
          </strong>
        </div>
      </div>

      {proposal.overall_rationale && (
        <div
          style={{
            fontSize: 12,
            padding: 8,
            background: 'var(--bg-primary)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            marginBottom: 8,
            lineHeight: 1.5,
          }}
        >
          {proposal.overall_rationale}
        </div>
      )}

      <div style={{ display: 'grid', gap: 8 }}>
        {proposal.proposed_groups.map((g, i) => (
          <div
            key={i}
            style={{
              background: 'var(--bg-primary)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              padding: 10,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--gold)' }}>
              {g.proposed_archetype_name || '(no name)'}
            </div>
            {g.role_description && (
              <div
                style={{
                  fontSize: 11,
                  color: 'var(--text-secondary)',
                  fontStyle: 'italic',
                  marginTop: 2,
                }}
              >
                {g.role_description}
              </div>
            )}
            <div style={{ fontSize: 11, marginTop: 6 }}>
              <strong>Members ({g.members.length}):</strong> {g.members.join(', ')}
            </div>
            {g.rationale && (
              <div style={{ fontSize: 11, marginTop: 6, lineHeight: 1.5 }}>
                <strong>Rationale:</strong> {g.rationale}
              </div>
            )}
            {g.evidence && g.evidence.length > 0 && (
              <ul
                style={{
                  fontSize: 11,
                  margin: '4px 0 0 16px',
                  padding: 0,
                  color: 'var(--text-secondary)',
                }}
              >
                {g.evidence.map((e, j) => (
                  <li key={j}>{e}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      {isActionable && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
          <button
            disabled={working}
            onClick={onApprove}
            style={{
              flex: 1,
              padding: '8px 14px',
              fontSize: 12,
              fontWeight: 700,
              background: '#16a34a',
              color: 'white',
              border: 'none',
              borderRadius: 4,
              cursor: working ? 'wait' : 'pointer',
              opacity: working ? 0.6 : 1,
            }}
          >
            Approve
          </button>
          <button
            disabled={working}
            onClick={onReject}
            style={{
              flex: 1,
              padding: '8px 14px',
              fontSize: 12,
              fontWeight: 700,
              background: 'transparent',
              color: '#f87171',
              border: '1px solid #f87171',
              borderRadius: 4,
              cursor: working ? 'wait' : 'pointer',
              opacity: working ? 0.6 : 1,
            }}
          >
            Reject
          </button>
        </div>
      )}

      {proposal.applied_note && (
        <div
          style={{
            marginTop: 8,
            fontSize: 10.5,
            color: 'var(--text-secondary)',
            fontFamily: 'monospace',
          }}
        >
          {proposal.applied_note}
        </div>
      )}
    </div>
  )
}

function ArchetypeCard({
  arch,
  dossiersByNorm,
  proposal,
  onApprove,
  onReject,
  workingId,
}: {
  arch: ArchetypeEntry
  dossiersByNorm: Map<string, DeityDossier>
  proposal: ArchetypeMergeProposal | null
  onApprove: (id: string) => void
  onReject: (id: string) => void
  workingId: string | null
}) {
  const [expanded, setExpanded] = useState(false)
  const [tab, setTab] = useState<CardTab>('map')

  const actorDossiers = useMemo(() => {
    return arch.actors
      .map(a => dossiersByNorm.get(normalizeName(a.name)) || null)
      .filter((d): d is DeityDossier => d != null)
  }, [arch.actors, dossiersByNorm])

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
            {expanded ? 'Collapse' : 'Expand'}
          </button>
        </div>
      </div>
      <div
        style={{
          display: 'flex',
          gap: 0,
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-tertiary)',
        }}
      >
        {(['map', 'dossiers', 'proposal'] as CardTab[]).map(t => {
          const isActive = tab === t
          const label =
            t === 'map'
              ? 'Map'
              : t === 'dossiers'
              ? `Dossiers (${actorDossiers.length})`
              : `Proposal${
                  proposal && proposal.status === 'pending'
                    ? ' •'
                    : proposal && proposal.status === 'applied'
                    ? ' ✓'
                    : ''
                }`
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                padding: '6px 14px',
                fontSize: 11,
                background: isActive ? 'var(--bg-primary)' : 'transparent',
                border: 'none',
                borderBottom: isActive
                  ? '2px solid var(--gold)'
                  : '2px solid transparent',
                color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontWeight: isActive ? 700 : 400,
              }}
            >
              {label}
            </button>
          )
        })}
      </div>
      <div
        style={{
          padding: 12,
          background: 'var(--bg-primary)',
        }}
      >
        {tab === 'map' && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: expanded ? '360px 1fr' : '1fr',
              gap: 14,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <MiniMindMap arch={arch} />
            </div>
            {expanded && (
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns:
                    'repeat(auto-fill, minmax(220px, 1fr))',
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
        )}

        {tab === 'dossiers' && (
          <div style={{ maxHeight: 520, overflowY: 'auto', paddingRight: 4 }}>
            {actorDossiers.length === 0 && (
              <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                No dossiers built for this archetype's actors yet. Run{' '}
                <code>POST /admin/build-deity-dossiers?epoch_orders=0</code>.
              </div>
            )}
            {actorDossiers.map(d => (
              <DossierPanel key={d.id} dossier={d} />
            ))}
          </div>
        )}

        {tab === 'proposal' && (
          <ProposalPanel
            proposal={proposal}
            onApprove={() => proposal && onApprove(proposal.id)}
            onReject={() => proposal && onReject(proposal.id)}
            working={workingId !== null && proposal?.id === workingId}
          />
        )}
      </div>
    </div>
  )
}

export default function ActorsPage() {
  const [data, setData] = useState<ArchetypeEntry[] | null>(null)
  const [dossiers, setDossiers] = useState<DeityDossier[] | null>(null)
  const [proposals, setProposals] = useState<ArchetypeMergeProposal[] | null>(
    null
  )
  const [err, setErr] = useState<string | null>(null)
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<SortMode>('events_desc')
  const [filter, setFilter] = useState<FilterMode>('with_events')
  const [workingProposalId, setWorkingProposalId] = useState<string | null>(
    null
  )
  const [banner, setBanner] = useState<string | null>(null)

  const loadAll = async () => {
    try {
      const [aRes, dRes, pRes] = await Promise.all([
        fetch('/world-api/story/archetype-analysis'),
        fetch('/world-api/story/deity-dossiers?epoch_order=0'),
        fetch('/world-api/story/archetype-proposals?epoch_order=0'),
      ])
      if (!aRes.ok) throw new Error(`archetype-analysis ${aRes.status}`)
      setData(await aRes.json())
      setDossiers(dRes.ok ? await dRes.json() : [])
      setProposals(pRes.ok ? await pRes.json() : [])
    } catch (e) {
      setErr(String(e))
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const dossiersByNorm = useMemo(() => {
    const m = new Map<string, DeityDossier>()
    for (const d of dossiers || []) m.set(d.normalized_name, d)
    return m
  }, [dossiers])

  const proposalByArchetypeId = useMemo(() => {
    const m = new Map<string, ArchetypeMergeProposal>()
    for (const p of proposals || []) {
      for (const aid of p.source_archetype_ids) {
        // Prefer the most recent pending proposal; fall back to applied.
        const existing = m.get(aid)
        if (!existing) {
          m.set(aid, p)
        } else {
          const rank = (x: ArchetypeMergeProposal) =>
            x.status === 'pending' ? 3 : x.status === 'applied' ? 2 : 1
          if (rank(p) > rank(existing)) m.set(aid, p)
        }
      }
    }
    return m
  }, [proposals])

  const runAdmin = async (
    path: string,
    successMsg: string,
    refetch = false
  ) => {
    setBanner(`Running ${path}…`)
    try {
      const r = await fetch(`/world-api${path}`, { method: 'POST' })
      if (!r.ok) throw new Error(`${r.status}`)
      const body = await r.json().catch(() => ({}))
      setBanner(`${successMsg} ${body.message || ''}`.trim())
      if (refetch) {
        // The build/propose endpoints run in the background; give them a
        // moment then refresh.
        setTimeout(loadAll, 2000)
      }
    } catch (e) {
      setBanner(`Error: ${e}`)
    }
  }

  const handleApprove = async (proposalId: string) => {
    setWorkingProposalId(proposalId)
    setBanner('Applying proposal…')
    try {
      const r = await fetch(
        `/world-api/admin/archetype-proposals/${proposalId}/approve`,
        { method: 'POST' }
      )
      if (!r.ok) {
        const body = await r.text()
        throw new Error(`${r.status}: ${body}`)
      }
      setBanner('Proposal applied. Refreshing…')
      await loadAll()
    } catch (e) {
      setBanner(`Error applying proposal: ${e}`)
    } finally {
      setWorkingProposalId(null)
    }
  }

  const handleReject = async (proposalId: string) => {
    setWorkingProposalId(proposalId)
    setBanner('Rejecting proposal…')
    try {
      const r = await fetch(
        `/world-api/admin/archetype-proposals/${proposalId}/reject`,
        { method: 'POST' }
      )
      if (!r.ok) throw new Error(`${r.status}`)
      setBanner('Proposal rejected.')
      await loadAll()
    } catch (e) {
      setBanner(`Error rejecting proposal: ${e}`)
    } finally {
      setWorkingProposalId(null)
    }
  }

  const filtered = useMemo(() => {
    if (!data) return []
    let items = [...data]
    if (filter === 'multi') {
      items = items.filter(a => a.actor_count >= 2)
    } else if (filter === 'problems') {
      items = items.filter(
        a =>
          a.total_event_count > 0 &&
          a.cohesion_score !== null &&
          a.cohesion_score < 45
      )
    } else if (filter === 'with_events') {
      items = items.filter(a => a.total_event_count > 0)
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
    } else if (sort === 'events_desc') {
      items.sort((a, b) => b.total_event_count - a.total_event_count)
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
            <option value="with_events">With events (active)</option>
            <option value="multi">Multi-actor only</option>
            <option value="problems">Low cohesion (under 45%)</option>
            <option value="all">All archetypes (incl. empty)</option>
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
            <option value="events_desc">Event count</option>
            <option value="cohesion_asc">Cohesion (low → high)</option>
            <option value="cohesion_desc">Cohesion (high → low)</option>
            <option value="size_desc">Actor count</option>
            <option value="name">Alphabetical</option>
          </select>
          <div style={{ flex: 1 }} />
          <button
            onClick={() =>
              runAdmin(
                '/admin/build-deity-dossiers?epoch_orders=0&wipe=true',
                'Dossier build started.',
                true
              )
            }
            style={toolbarBtnStyle}
          >
            Build dossiers
          </button>
          <button
            onClick={() =>
              runAdmin(
                '/admin/propose-archetype-remerges?epoch_orders=0&wipe_pending=true',
                'Proposal generation started.',
                true
              )
            }
            style={toolbarBtnStyle}
          >
            Propose re-merges
          </button>
          <button
            onClick={() =>
              runAdmin(
                '/admin/run-narrative-v2?epoch_orders=0&phase=render_only',
                'Re-render started.',
                false
              )
            }
            style={toolbarBtnStyle}
          >
            Re-render chapters
          </button>
          <button onClick={loadAll} style={toolbarBtnStyle}>
            Refresh
          </button>
        </div>
        {banner && (
          <div
            style={{
              marginTop: 8,
              fontSize: 11,
              padding: '6px 10px',
              background: 'var(--bg-primary)',
              border: '1px solid var(--border)',
              borderRadius: 4,
              color: 'var(--text-secondary)',
              fontFamily: 'monospace',
            }}
          >
            {banner}
          </div>
        )}
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
            <ArchetypeCard
              key={a.archetype_id}
              arch={a}
              dossiersByNorm={dossiersByNorm}
              proposal={proposalByArchetypeId.get(a.archetype_id) || null}
              onApprove={handleApprove}
              onReject={handleReject}
              workingId={workingProposalId}
            />
          ))}
        </div>
      </div>
    </div>
  )
}

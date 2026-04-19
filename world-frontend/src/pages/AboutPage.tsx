import { useState, useEffect } from 'react'
import { api } from '../api'
import type { StoryStats } from '../api'

const LAWS = [
  {
    num: 1,
    name: 'Myth as Recorded Memory',
    desc: 'Every surviving myth, text, and oral tradition is treated as a record of perceived events — not metaphor, not fiction, not misunderstanding. We do not dismiss. We do not blindly literalize. We treat it as data input.',
  },
  {
    num: 2,
    name: 'Source-Only Input Law',
    desc: 'The system may only use information derived from ingested source materials. No modern theory, no external explanation, no inferred intent from analysts, commentators, or academics.',
  },
  {
    num: 3,
    name: 'No Interpretation Injection',
    desc: 'No meaning, purpose, motive, symbolism, or causation ("why") may be introduced unless explicitly present in a source text or artifact. The system describes what the sources say — never why they said it.',
  },
  {
    num: 4,
    name: 'Age-Weighted Priority Law',
    desc: 'Earlier recorded versions of a narrative carry higher weight. Later versions are supporting evidence, not overrides. A source closer in time to the events described is structurally more authoritative.',
  },
  {
    num: 5,
    name: 'Cross-Cultural Convergence Law',
    desc: 'Independent recurrence of a pattern or claim across geographically separated or culturally independent sources significantly increases its structural weight. Requirements: geographic separation or cultural independence, and similar structural form (not just vague similarity).',
  },
  {
    num: 6,
    name: 'Distribution Independence Law',
    desc: 'The frequency, popularity, or modern prevalence of a narrative does not increase its truth weight. Having 50 records from one tradition does not outweigh 2 records from 2 independent traditions.',
  },
  {
    num: 7,
    name: 'Pattern Dominance Law',
    desc: 'Recurring structural patterns outweigh isolated claims. A one-off claim from a single source = weak. A repeated structure across multiple sources = strong. The system prioritizes patterns over individual assertions.',
  },
  {
    num: 8,
    name: 'Entity Convergence Law',
    desc: 'Entities from different cultures that share aligned structural roles, attributes, and narrative functions may be merged. The four criteria: role similarity, action similarity, context alignment, and pattern repetition — all must be satisfied.',
  },
  {
    num: 9,
    name: 'Minimal Assumption Law',
    desc: 'When multiple interpretations are possible, select the one requiring the fewest unsupported assumptions. Occam\'s razor applied to ancient history.',
  },
  {
    num: 10,
    name: 'Narrative Continuity Law',
    desc: 'Construct a single continuous timeline that integrates all compatible sources without contradiction. No "this culture says / that culture says" framing — instead, a unified narrative with merged or parallel threads.',
  },
  {
    num: 11,
    name: 'Contradiction Handling Law',
    desc: 'When sources directly conflict on a claim, the system prioritizes the older source with stronger pattern support. If irreconcilable, both accounts are maintained as parallel threads within the same timeline.',
  },
  {
    num: 12,
    name: 'Structural Consistency Law',
    desc: 'Once an entity, event, or pattern is established in the narrative, it must remain consistent across all subsequent outputs. No contradictory recharacterizations.',
  },
  {
    num: 13,
    name: 'Image Constraint Law',
    desc: 'Visual evidence (artifacts, carvings, paintings) informs environment and material context but cannot by itself define narrative meaning. Images support — they do not override textual sources.',
  },
  {
    num: 14,
    name: 'Traceability Law',
    desc: 'Every narrative element, claim, or assertion must be traceable to at least one source record or identifiable pattern cluster. Nothing enters the narrative without evidence.',
  },
  {
    num: 15,
    name: 'Synthesis Constraint Law',
    desc: 'Sources may be combined into a unified narrative only where compatibility exists. Where sources are incompatible, they are layered or parallelized — never forced into agreement.',
  },
  {
    num: 16,
    name: 'Ancient Time Anchoring Law',
    desc: 'Ancient sources\' own timelines, sequences, and chronological frameworks are prioritized over modern chronological reconstructions when conflicts arise.',
  },
]

export default function AboutPage() {
  const [stats, setStats] = useState<StoryStats | null>(null)

  useEffect(() => {
    api.getStoryStats().then(setStats).catch(console.error)
  }, [])

  return (
    <div style={{
      height: '100%',
      overflow: 'auto',
      background: 'var(--bg-primary)',
    }}>
      <div style={{ maxWidth: 800, margin: '0 auto', padding: '48px 24px 120px' }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: 48 }}>
          <h1 style={{
            fontSize: 32,
            fontWeight: 700,
            color: 'var(--gold)',
            fontFamily: "'Georgia', 'Times New Roman', serif",
            marginBottom: 12,
          }}>
            How We Digest History
          </h1>
          <p style={{
            fontSize: 16,
            color: 'var(--text-secondary)',
            lineHeight: 1.7,
            maxWidth: 600,
            margin: '0 auto',
          }}>
            EDIN synthesizes a unified account of human origin and history from the world's
            oldest surviving texts, artifacts, and traditions — governed by 16 immutable laws
            that ensure source fidelity, cross-cultural fairness, and structural integrity.
          </p>
        </div>

        {/* Stats Grid */}
        {stats && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            gap: 12,
            marginBottom: 48,
          }}>
            {[
              { label: 'Source Records', value: stats.total_source_records },
              { label: 'Images', value: stats.total_images },
              { label: 'Cultures', value: stats.total_cultures },
              { label: 'Languages', value: stats.total_languages },
              { label: 'Segments', value: stats.total_segments },
              { label: 'Planned Chapters', value: stats.total_planned_chapters },
              { label: 'Written Chapters', value: stats.total_story_chapters },
              { label: 'Total Words', value: stats.total_words },
              { label: 'Epochs', value: stats.total_epochs },
              { label: 'Canonical Actors', value: stats.total_canonical_actors },
              { label: 'Canonical Events', value: stats.total_canonical_events },
              { label: 'Canonical Places', value: stats.total_canonical_places },
            ].map(stat => (
              <div key={stat.label} style={{
                padding: '16px',
                background: 'var(--bg-secondary)',
                borderRadius: 8,
                border: '1px solid var(--border)',
                textAlign: 'center',
              }}>
                <div style={{
                  fontSize: 24,
                  fontWeight: 700,
                  color: 'var(--gold)',
                  fontFamily: 'monospace',
                }}>
                  {stat.value.toLocaleString()}
                </div>
                <div style={{
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: 0.5,
                  marginTop: 4,
                }}>
                  {stat.label}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* The 16 Laws */}
        <div>
          <h2 style={{
            fontSize: 22,
            fontWeight: 700,
            color: 'var(--text-primary)',
            fontFamily: "'Georgia', 'Times New Roman', serif",
            marginBottom: 8,
            textAlign: 'center',
          }}>
            The 16 Laws
          </h2>
          <p style={{
            fontSize: 14,
            color: 'var(--text-secondary)',
            textAlign: 'center',
            marginBottom: 32,
            lineHeight: 1.6,
          }}>
            These laws govern every aspect of synthesis — from data ingestion to narrative output.
            They cannot be overridden by any model, prompt, or user request.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {LAWS.map(law => (
              <div key={law.num} style={{
                padding: '20px 24px',
                background: 'var(--bg-secondary)',
                borderRadius: 8,
                border: '1px solid var(--border)',
                borderLeft: '3px solid var(--gold)',
              }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 8 }}>
                  <span style={{
                    fontSize: 14,
                    fontWeight: 700,
                    color: 'var(--gold)',
                    fontFamily: 'monospace',
                    minWidth: 28,
                  }}>
                    {String(law.num).padStart(2, '0')}
                  </span>
                  <h3 style={{
                    fontSize: 16,
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                  }}>
                    {law.name}
                  </h3>
                </div>
                <p style={{
                  fontSize: 14,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.7,
                  marginLeft: 40,
                }}>
                  {law.desc}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* Scoring Methodology */}
        <div style={{ marginTop: 48 }}>
          <h2 style={{
            fontSize: 22,
            fontWeight: 700,
            color: 'var(--text-primary)',
            fontFamily: "'Georgia', 'Times New Roman', serif",
            marginBottom: 16,
            textAlign: 'center',
          }}>
            Scoring Methodology
          </h2>
          <div style={{
            padding: '24px',
            background: 'var(--bg-secondary)',
            borderRadius: 8,
            border: '1px solid var(--border)',
          }}>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.7, marginBottom: 16 }}>
              Every entity, event, and claim is scored using a 6-factor formula:
            </p>
            <code style={{
              display: 'block',
              padding: '16px',
              background: 'var(--bg-tertiary)',
              borderRadius: 6,
              fontFamily: 'monospace',
              fontSize: 13,
              color: 'var(--gold)',
              lineHeight: 1.6,
              marginBottom: 16,
            }}>
              final = (age × 0.25) + (corroboration × 0.20) + (independence × 0.20)<br />
              {'      '}+ (citation × 0.15) + (pattern × 0.10) − (ambiguity × 0.10)
            </code>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              {[
                { factor: 'Age (25%)', desc: 'Older sources receive higher weight' },
                { factor: 'Corroboration (20%)', desc: 'Volume of supporting evidence, normalized per culture' },
                { factor: 'Independence (20%)', desc: 'Number of distinct cultures citing this entity' },
                { factor: 'Citation (15%)', desc: 'Later sources referencing older events add credence' },
                { factor: 'Pattern (10%)', desc: 'Motif recurrence across independent cultures' },
                { factor: 'Ambiguity (−10%)', desc: 'Contradictions and low merge confidence as penalty' },
              ].map(f => (
                <div key={f.factor} style={{ padding: 10, background: 'var(--bg-tertiary)', borderRadius: 6 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', marginBottom: 2 }}>
                    {f.factor}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{f.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

import type { SourceSet } from '../../api'

export default function SourceCard({ source }: { source: SourceSet }) {
  return (
    <div style={{
      background: 'var(--bg-tertiary)',
      border: '1px solid var(--border)',
      borderRadius: '6px',
      padding: '12px',
      marginBottom: '8px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <h4 style={{
          fontSize: '13px',
          fontWeight: 600,
          color: 'var(--text-primary)',
          lineHeight: 1.3,
          flex: 1,
        }}>
          {source.title || 'Untitled Source'}
        </h4>
        <span style={{
          fontSize: '10px',
          padding: '2px 6px',
          borderRadius: '3px',
          background: 'rgba(99, 102, 241, 0.15)',
          color: 'var(--accent)',
          fontWeight: 600,
          marginLeft: '8px',
          whiteSpace: 'nowrap',
        }}>
          {(source.relevance_weight * 100).toFixed(0)}%
        </span>
      </div>

      {source.source_type && (
        <div style={{
          fontSize: '11px',
          color: 'var(--text-muted)',
          marginTop: '4px',
          textTransform: 'capitalize',
        }}>
          {source.source_type.replace(/_/g, ' ')}
        </div>
      )}

      {source.excerpt && (
        <p style={{
          fontSize: '12px',
          color: 'var(--text-secondary)',
          marginTop: '8px',
          lineHeight: 1.5,
          fontStyle: 'italic',
          borderLeft: '2px solid var(--accent)',
          paddingLeft: '8px',
        }}>
          {source.excerpt.slice(0, 200)}
          {source.excerpt.length > 200 && '...'}
        </p>
      )}
    </div>
  )
}

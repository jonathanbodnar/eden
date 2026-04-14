import type { ArtifactSet } from '../../api'

export default function ArtifactCard({ artifact }: { artifact: ArtifactSet }) {
  return (
    <div style={{
      background: 'var(--bg-tertiary)',
      border: '1px solid var(--border)',
      borderRadius: '6px',
      padding: '12px',
      marginBottom: '8px',
    }}>
      <div style={{ display: 'flex', gap: '10px' }}>
        {artifact.image_url && (
          <img
            src={artifact.image_url}
            alt={artifact.title || 'Artifact'}
            style={{
              width: '60px',
              height: '60px',
              objectFit: 'cover',
              borderRadius: '4px',
              border: '1px solid var(--border)',
            }}
          />
        )}
        <div style={{ flex: 1, minWidth: 0 }}>
          <h4 style={{
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--text-primary)',
            lineHeight: 1.3,
          }}>
            {artifact.title || 'Untitled Artifact'}
          </h4>
          {artifact.description && (
            <p style={{
              fontSize: '12px',
              color: 'var(--text-secondary)',
              marginTop: '4px',
              lineHeight: 1.4,
            }}>
              {artifact.description.slice(0, 120)}
              {artifact.description.length > 120 && '...'}
            </p>
          )}
          <div style={{
            display: 'flex',
            gap: '12px',
            marginTop: '6px',
          }}>
            {artifact.location && (
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                {artifact.location}
              </span>
            )}
            {artifact.date_label && (
              <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                {artifact.date_label}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

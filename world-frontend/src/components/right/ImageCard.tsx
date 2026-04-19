import type { ImageSet } from '../../api'

export default function ImageCard({ image }: { image: ImageSet }) {
  return (
    <div style={{
      background: 'var(--bg-tertiary)',
      border: '1px solid var(--border)',
      borderRadius: '6px',
      overflow: 'hidden',
    }}>
      {image.image_url ? (
        <img
          src={image.image_url}
          alt={image.caption || 'Image'}
          style={{
            width: '100%',
            height: '120px',
            objectFit: 'cover',
          }}
        />
      ) : (
        <div style={{
          width: '100%',
          height: '120px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg-primary)',
          color: 'var(--text-muted)',
          fontSize: '11px',
        }}>
          No image
        </div>
      )}
      {image.caption && (
        <div style={{
          padding: '8px',
          fontSize: '11px',
          color: 'var(--text-secondary)',
          lineHeight: 1.4,
        }}>
          {image.caption}
        </div>
      )}
    </div>
  )
}

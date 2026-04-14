import { useWorldContext } from '../../context/WorldContext'
import EpochAccordion from './EpochAccordion'

export default function LeftPanel() {
  const { epochs, epochsLoading } = useWorldContext()

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '16px 14px 10px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <h1 style={{
          fontSize: '14px',
          fontWeight: 700,
          color: 'var(--gold)',
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
        }}>
          Edinworld
        </h1>
        <p style={{
          fontSize: '10px',
          color: 'var(--text-muted)',
          marginTop: '2px',
        }}>
          Canon Explorer
        </p>
      </div>

      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '4px 0',
      }}>
        {epochsLoading ? (
          <div style={{ padding: '20px 14px', color: 'var(--text-muted)', fontSize: '12px' }}>
            Loading epochs...
          </div>
        ) : epochs.length === 0 ? (
          <div style={{ padding: '20px 14px', color: 'var(--text-muted)', fontSize: '12px' }}>
            No epochs found. Run the synthesis pipeline to generate canon data.
          </div>
        ) : (
          epochs.map(epoch => (
            <EpochAccordion key={epoch.id} epoch={epoch} />
          ))
        )}
      </div>
    </div>
  )
}

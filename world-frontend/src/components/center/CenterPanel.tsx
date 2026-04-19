import { useWorldContext } from '../../context/WorldContext'
import EpochView from './EpochView'
import CultureView from './CultureView'
import ChapterView from './ChapterView'

export default function CenterPanel() {
  const { activeEpochId, epochOverview, epochLoading, activeCulture, activeChapterId, chapterDetail, chapterLoading } = useWorldContext()

  if (epochLoading || chapterLoading) {
    return (
      <div style={{
        position: 'relative',
        height: '100%',
        overflow: 'hidden',
        background: 'var(--bg-primary)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: '12px',
          animation: 'fadeIn 0.3s',
        }}>
          <div style={{
            width: '32px',
            height: '32px',
            border: '2px solid var(--border)',
            borderTopColor: 'var(--accent)',
            borderRadius: '50%',
            animation: 'pulse 1s infinite',
          }} />
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Loading...</span>
        </div>
      </div>
    )
  }

  if (activeChapterId && chapterDetail) {
    return <ChapterView />
  }

  if (activeCulture) {
    return <CultureView />
  }

  if (activeEpochId && epochOverview) {
    return <EpochView />
  }

  return (
    <div style={{
      position: 'relative',
      height: '100%',
      overflow: 'hidden',
      background: `radial-gradient(ellipse at 50% 50%, rgba(99, 102, 241, 0.06) 0%, var(--bg-primary) 70%)`,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
    }}>
      <div style={{ textAlign: 'center', maxWidth: '420px', animation: 'fadeIn 0.5s' }}>
        <div style={{
          width: '72px',
          height: '72px',
          borderRadius: '50%',
          border: '1.5px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 20px',
          background: 'var(--bg-secondary)',
        }}>
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--gold)" strokeWidth="1.2">
            <circle cx="12" cy="12" r="10" />
            <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
          </svg>
        </div>
        <h2 style={{
          fontSize: '16px',
          fontWeight: 600,
          color: 'var(--text-primary)',
          marginBottom: '6px',
        }}>
          Ancient World Explorer
        </h2>
        <p style={{
          fontSize: '12px',
          color: 'var(--text-muted)',
          lineHeight: 1.6,
        }}>
          Select an epoch from the left panel or the timeline below to explore civilizations, events, and artifacts from the ancient world.
        </p>
      </div>
    </div>
  )
}

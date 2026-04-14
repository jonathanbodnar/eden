import { useState } from 'react'
import type { Epoch } from '../../api'
import { useWorldContext } from '../../context/WorldContext'
import ChapterList from './ChapterList'

function formatYear(y: number | null): string {
  if (y === null) return '?'
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

export default function EpochAccordion({ epoch }: { epoch: Epoch }) {
  const [chaptersOpen, setChaptersOpen] = useState(false)
  const { activeEpochId, selectEpoch } = useWorldContext()
  const isActive = activeEpochId === epoch.id

  const handleClick = () => {
    selectEpoch(epoch.id)
    setChaptersOpen(prev => isActive ? !prev : true)
  }

  return (
    <div style={{
      borderBottom: '1px solid var(--border)',
    }}>
      <button
        onClick={handleClick}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 14px',
          border: 'none',
          background: isActive
            ? 'linear-gradient(90deg, rgba(99,102,241,0.12), transparent)'
            : 'transparent',
          cursor: 'pointer',
          transition: 'background 0.15s',
          textAlign: 'left',
          borderLeft: isActive ? '3px solid var(--accent)' : '3px solid transparent',
        }}
        onMouseEnter={e => {
          if (!isActive) (e.currentTarget as HTMLElement).style.background = 'var(--bg-hover)'
        }}
        onMouseLeave={e => {
          if (!isActive) (e.currentTarget as HTMLElement).style.background = 'transparent'
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: '12px',
            fontWeight: isActive ? 700 : 500,
            color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {epoch.title}
          </div>
          <div style={{
            fontSize: '10px',
            color: 'var(--text-muted)',
            marginTop: '1px',
          }}>
            {formatYear(epoch.time_start)} — {formatYear(epoch.time_end)}
            {epoch.chapter_count > 0 && (
              <span style={{ marginLeft: '6px', color: 'var(--accent)', fontWeight: 500 }}>
                {epoch.chapter_count} ch.
              </span>
            )}
          </div>
        </div>
        <span style={{
          color: 'var(--text-muted)',
          fontSize: '10px',
          marginLeft: '6px',
          transition: 'transform 0.15s',
          transform: chaptersOpen && isActive ? 'rotate(90deg)' : 'rotate(0deg)',
        }}>
          {epoch.chapter_count > 0 ? '▶' : ''}
        </span>
      </button>

      {chaptersOpen && isActive && epoch.chapter_count > 0 && (
        <ChapterList epochId={epoch.id} />
      )}
    </div>
  )
}

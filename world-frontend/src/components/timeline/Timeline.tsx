import { useRef, useEffect, useCallback } from 'react'
import { useWorldContext } from '../../context/WorldContext'
import type { Epoch } from '../../api'

function formatYear(y: number | null): string {
  if (y === null) return '?'
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

const EPOCH_COLORS: Record<string, string> = {
  'Creation': '#4c1d95',
  'Gods': '#7c3aed',
  'Flood': '#0284c7',
  'Antediluvian': '#059669',
  'Dawn': '#d97706',
  'Cities': '#dc2626',
  'Empires': '#be123c',
  'Heroes': '#c026d3',
  'Iron': '#0d9488',
  'Classical': '#6366f1',
  'Undated': '#6b7280',
}

function getColor(title: string): string {
  for (const [key, color] of Object.entries(EPOCH_COLORS)) {
    if (title.includes(key)) return color
  }
  return '#6366f1'
}

export default function Timeline() {
  const { epochs, activeEpochId, selectEpoch } = useWorldContext()
  const scrollRef = useRef<HTMLDivElement>(null)

  const datable = epochs.filter(e => e.time_start !== null && e.time_end !== null)
  const mythic = epochs.filter(e => e.time_start === null || e.time_end === null)

  const minYear = datable.length > 0 ? Math.min(...datable.map(e => e.time_start!)) : -5000
  const maxYear = datable.length > 0 ? Math.max(...datable.map(e => e.time_end!)) : 0
  const totalSpan = maxYear - minYear || 1

  const scrollToActive = useCallback(() => {
    if (!scrollRef.current || !activeEpochId) return
    const el = scrollRef.current.querySelector(`[data-epoch="${activeEpochId}"]`) as HTMLElement | null
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
    }
  }, [activeEpochId])

  useEffect(() => {
    scrollToActive()
  }, [scrollToActive])

  const renderEpoch = (epoch: Epoch, widthPct?: number) => {
    const isActive = epoch.id === activeEpochId
    const color = getColor(epoch.title)

    return (
      <button
        key={epoch.id}
        data-epoch={epoch.id}
        onClick={() => selectEpoch(epoch.id)}
        style={{
          flex: widthPct ? `0 0 ${Math.max(widthPct, 6)}%` : '0 0 80px',
          height: '100%',
          border: 'none',
          cursor: 'pointer',
          padding: '8px 10px 6px',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          position: 'relative',
          background: isActive
            ? `linear-gradient(to bottom, ${color}40, ${color}15)`
            : 'transparent',
          borderTop: isActive ? `2px solid ${color}` : '2px solid transparent',
          transition: 'all 0.2s',
          overflow: 'hidden',
        }}
        onMouseEnter={e => {
          if (!isActive) {
            (e.currentTarget as HTMLElement).style.background = `${color}15`
            ;(e.currentTarget as HTMLElement).style.borderTopColor = `${color}60`
          }
        }}
        onMouseLeave={e => {
          if (!isActive) {
            (e.currentTarget as HTMLElement).style.background = 'transparent'
            ;(e.currentTarget as HTMLElement).style.borderTopColor = 'transparent'
          }
        }}
      >
        <div style={{
          fontSize: '10px',
          fontWeight: isActive ? 700 : 500,
          color: isActive ? color : 'var(--text-secondary)',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          letterSpacing: '0.02em',
        }}>
          {epoch.title}
        </div>
        <div style={{
          fontSize: '9px',
          color: 'var(--text-muted)',
          whiteSpace: 'nowrap',
        }}>
          {formatYear(epoch.time_start)} — {formatYear(epoch.time_end)}
        </div>
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: '3px',
          background: color,
          opacity: isActive ? 0.8 : 0.2,
          transition: 'opacity 0.2s',
        }} />
      </button>
    )
  }

  return (
    <div style={{
      height: 'var(--timeline-height)',
      background: 'var(--bg-secondary)',
      borderTop: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
    }}>
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          display: 'flex',
          overflowX: 'auto',
          overflowY: 'hidden',
          scrollbarWidth: 'none',
        }}
      >
        {mythic.map(e => renderEpoch(e))}
        {mythic.length > 0 && datable.length > 0 && (
          <div style={{
            width: '1px',
            background: 'var(--border)',
            flexShrink: 0,
          }} />
        )}
        {datable.map(e => {
          const span = (e.time_end! - e.time_start!) / totalSpan * 100
          return renderEpoch(e, span)
        })}
      </div>
    </div>
  )
}

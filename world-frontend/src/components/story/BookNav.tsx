import { useState } from 'react'
import type { StoryChapter, StoryEpoch } from '../../api'

interface Props {
  epochs: StoryEpoch[]
  chapters: StoryChapter[]
  activeChapterId: string | null
  onSelectChapter: (id: string) => void
  onClose?: () => void
}

function formatDate(y: number | null): string {
  if (y === null) return ''
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

export default function BookNav({ epochs, chapters, activeChapterId, onSelectChapter, onClose }: Props) {
  const [expandedEpoch, setExpandedEpoch] = useState<string | null>(
    epochs.length > 0 ? epochs[0].id : null
  )

  const totalChapters = chapters.length
  const currentIdx = chapters.findIndex(c => c.id === activeChapterId)
  const progress = totalChapters > 0 ? ((currentIdx + 1) / totalChapters) * 100 : 0

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
        padding: '16px 16px 12px',
        borderBottom: '1px solid var(--border)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 1.5 }}>
            Table of Contents
          </div>
          {onClose && (
            <button
              onClick={onClose}
              style={{
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'var(--text-muted)', fontSize: 18, padding: 0, lineHeight: 1,
              }}
            >
              &times;
            </button>
          )}
        </div>
        <div style={{
          height: 3,
          background: 'var(--bg-tertiary)',
          borderRadius: 2,
          overflow: 'hidden',
        }}>
          <div style={{
            height: '100%',
            width: `${progress}%`,
            background: 'var(--gold)',
            borderRadius: 2,
            transition: 'width 0.3s ease',
          }} />
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>
          {currentIdx + 1} of {totalChapters} chapters
        </div>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '8px 0' }}>
        {epochs.map((epoch, epochIdx) => {
          const epochChapters = chapters.filter(c => c.epoch_id === epoch.id)
          if (epochChapters.length === 0) return null
          const isExpanded = expandedEpoch === epoch.id

          return (
            <div key={epoch.id} style={{ marginBottom: 2 }}>
              <button
                onClick={() => setExpandedEpoch(isExpanded ? null : epoch.id)}
                style={{
                  width: '100%',
                  padding: '10px 16px',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: 8,
                  background: isExpanded ? 'var(--bg-tertiary)' : 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                  textAlign: 'left',
                }}
              >
                <span style={{
                  fontSize: 11,
                  color: 'var(--gold)',
                  fontWeight: 700,
                  minWidth: 24,
                  flexShrink: 0,
                }}>
                  {String.fromCharCode(8544 + epochIdx)}
                </span>
                <div>
                  <div style={{
                    fontSize: 13,
                    fontWeight: 600,
                    color: isExpanded ? 'var(--text-primary)' : 'var(--text-secondary)',
                    lineHeight: 1.3,
                  }}>
                    {epoch.title}
                  </div>
                  {epoch.time_start !== null && (
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      {formatDate(epoch.time_start)} — {formatDate(epoch.time_end)}
                    </div>
                  )}
                </div>
              </button>

              {isExpanded && (
                <div style={{ padding: '0 0 8px' }}>
                  {epochChapters.map((ch, chIdx) => {
                    const isActive = ch.id === activeChapterId
                    return (
                      <button
                        key={ch.id}
                        onClick={() => onSelectChapter(ch.id)}
                        style={{
                          width: '100%',
                          padding: '6px 16px 6px 48px',
                          display: 'flex',
                          alignItems: 'baseline',
                          gap: 8,
                          background: isActive ? 'var(--accent-dim)' : 'transparent',
                          border: 'none',
                          borderLeft: isActive ? '2px solid var(--gold)' : '2px solid transparent',
                          cursor: 'pointer',
                          textAlign: 'left',
                        }}
                      >
                        <span style={{
                          fontSize: 11,
                          color: isActive ? 'var(--gold)' : 'var(--text-muted)',
                          fontWeight: 600,
                          minWidth: 18,
                        }}>
                          {chIdx + 1}.
                        </span>
                        <span style={{
                          fontSize: 12,
                          color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
                          fontWeight: isActive ? 500 : 400,
                          lineHeight: 1.4,
                        }}>
                          {ch.chapter_title}
                        </span>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

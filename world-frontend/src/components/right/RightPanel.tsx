import { useState } from 'react'
import { useWorldContext } from '../../context/WorldContext'
import EvidenceSection from './EvidenceSection'
import ChatSection from './ChatSection'

export default function RightPanel() {
  const [chatExpanded, setChatExpanded] = useState(false)
  const { activeEpochId } = useWorldContext()

  return (
    <div style={{
      background: 'var(--bg-secondary)',
      borderLeft: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '12px 14px 8px',
        borderBottom: '1px solid var(--border)',
        flexShrink: 0,
      }}>
        <div style={{
          fontSize: '11px',
          fontWeight: 600,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
        }}>
          Sources & Evidence
        </div>
      </div>

      <div style={{
        flex: 1,
        overflowY: 'auto',
        minHeight: 0,
      }}>
        {!activeEpochId ? (
          <div style={{
            padding: '32px 16px',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '12px',
          }}>
            Select an epoch to view sources and evidence used to construct this view of history.
          </div>
        ) : (
          <EvidenceSection />
        )}
      </div>

      <div style={{
        flexShrink: 0,
        borderTop: '1px solid var(--border)',
        display: 'flex',
        flexDirection: 'column',
        maxHeight: chatExpanded ? '50%' : '48px',
        transition: 'max-height 0.2s',
        overflow: 'hidden',
      }}>
        <ChatSection expanded={chatExpanded} onToggle={() => setChatExpanded(prev => !prev)} />
      </div>
    </div>
  )
}

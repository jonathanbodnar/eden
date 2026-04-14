import LeftPanel from '../components/left/LeftPanel'
import CenterPanel from '../components/center/CenterPanel'
import RightPanel from '../components/right/RightPanel'
import Timeline from '../components/timeline/Timeline'

export default function ThreePanelLayout() {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'var(--left-width) 1fr var(--right-width)',
      gridTemplateRows: '1fr var(--timeline-height)',
      height: '100vh',
      width: '100vw',
      overflow: 'hidden',
    }}>
      <LeftPanel />
      <CenterPanel />
      <RightPanel />
      <div style={{ gridColumn: '1 / -1' }}>
        <Timeline />
      </div>
    </div>
  )
}

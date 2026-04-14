import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import { WorldProvider } from './context/WorldContext'
import ThreePanelLayout from './layouts/ThreePanelLayout'
import StoryModeLayout from './layouts/StoryModeLayout'
import AboutPage from './pages/AboutPage'

function TabBar() {
  const location = useLocation()
  const navigate = useNavigate()
  const current = location.pathname.startsWith('/story')
    ? 'story'
    : location.pathname.startsWith('/about')
    ? 'about'
    : 'explorer'

  const tabs = [
    { key: 'explorer', label: 'Explorer', path: '/' },
    { key: 'story', label: 'Story', path: '/story' },
    { key: 'about', label: 'About', path: '/about' },
  ]

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      height: 40,
      background: 'var(--bg-secondary)',
      borderBottom: '1px solid var(--border)',
      padding: '0 16px',
      gap: 4,
      flexShrink: 0,
    }}>
      <span style={{
        fontSize: 14,
        fontWeight: 700,
        color: 'var(--gold)',
        marginRight: 20,
        letterSpacing: '0.5px',
      }}>
        EDIN
      </span>
      {tabs.map(t => (
        <button
          key={t.key}
          onClick={() => navigate(t.path)}
          style={{
            padding: '6px 16px',
            fontSize: 13,
            fontWeight: current === t.key ? 600 : 400,
            color: current === t.key ? 'var(--text-primary)' : 'var(--text-secondary)',
            background: current === t.key ? 'var(--bg-tertiary)' : 'transparent',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export default function App() {
  return (
    <WorldProvider>
      <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
        <TabBar />
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <Routes>
            <Route path="/story/*" element={<StoryModeLayout />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="/*" element={<ThreePanelLayout />} />
          </Routes>
        </div>
      </div>
    </WorldProvider>
  )
}

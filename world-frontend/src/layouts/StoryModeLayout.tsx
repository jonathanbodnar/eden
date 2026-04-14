import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import type { StoryChapter, StoryEpoch, StoryEvidence, CultureVariant } from '../api'
import BookNav from '../components/story/BookNav'
import NarrativeReader from '../components/story/NarrativeReader'
import EvidencePanel from '../components/story/EvidencePanel'
import AudioPlayerBar from '../components/story/AudioPlayerBar'
import { useMediaQuery, MOBILE, TABLET } from '../hooks/useMediaQuery'

export default function StoryModeLayout() {
  const isMobile = useMediaQuery(MOBILE)
  const isTablet = useMediaQuery(TABLET)
  const [epochs, setEpochs] = useState<StoryEpoch[]>([])
  const [chapters, setChapters] = useState<StoryChapter[]>([])
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<StoryEvidence[]>([])
  const [selectedEntity, setSelectedEntity] = useState<{
    entityType: string; entityId: string; entityName: string
  } | null>(null)
  const [activeCulture, setActiveCulture] = useState<CultureVariant | null>(null)
  const [loading, setLoading] = useState(true)

  const [leftOpen, setLeftOpen] = useState(false)
  const [rightOpen, setRightOpen] = useState(false)

  useEffect(() => {
    Promise.all([api.getStoryEpochs(), api.getStoryChapters()])
      .then(([ep, ch]) => {
        setEpochs(ep)
        setChapters(ch)
        if (ch.length > 0) setActiveChapterId(ch[0].id)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    if (!activeChapterId) return
    setSelectedEntity(null)
    api.getStoryChapterEvidence(activeChapterId)
      .then(setEvidence)
      .catch(() => setEvidence([]))
  }, [activeChapterId])

  const handleEntityClick = useCallback((entityType: string, entityId: string, entityName: string) => {
    setActiveCulture(null)
    setSelectedEntity({ entityType, entityId, entityName })
    if (isMobile || isTablet) setRightOpen(true)
  }, [isMobile, isTablet])

  const handleClearEntity = useCallback(() => {
    setSelectedEntity(null)
  }, [])

  const handleCultureSelect = useCallback((variant: CultureVariant | null) => {
    setActiveCulture(variant)
    if (variant) setSelectedEntity(null)
  }, [])

  const handleSelectChapter = useCallback((id: string) => {
    setActiveChapterId(id)
    if (isMobile) setLeftOpen(false)
  }, [isMobile])

  const handleAudioChapterChange = useCallback((chapterId: string) => {
    setActiveChapterId(chapterId)
  }, [])

  const activeChapter = chapters.find(c => c.id === activeChapterId) || null

  if (loading) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: 'var(--text-secondary)',
      }}>
        Loading narrative...
      </div>
    )
  }

  if (chapters.length === 0) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', flexDirection: 'column', gap: 12, color: 'var(--text-secondary)',
      }}>
        <div style={{ fontSize: 48 }}>&#128220;</div>
        <div style={{ fontSize: 18, fontWeight: 600 }}>No Narrative Generated Yet</div>
        <div style={{ fontSize: 14, maxWidth: 400, textAlign: 'center', lineHeight: 1.6 }}>
          Run the narrative synthesis pipeline from the admin panel to generate
          the unified ancient history.
        </div>
      </div>
    )
  }

  const compactHeader = isMobile || (isTablet && !leftOpen)

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* Mobile/Tablet header bar */}
      {compactHeader && (
        <div style={{
          height: 48,
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '0 12px',
          background: 'var(--bg-secondary)',
          borderBottom: '1px solid var(--border)',
          zIndex: 20,
        }}>
          <button
            onClick={() => setLeftOpen(!leftOpen)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: leftOpen ? 'var(--gold)' : 'var(--text-secondary)',
              fontSize: 20, padding: 4, lineHeight: 1,
            }}
            aria-label="Table of contents"
          >
            &#9776;
          </button>
          <div style={{
            flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            fontSize: 13, fontWeight: 600, color: 'var(--text-primary)',
          }}>
            {activeChapter?.chapter_title || 'EDIN'}
          </div>
          <button
            onClick={() => setRightOpen(!rightOpen)}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: rightOpen ? 'var(--gold)' : 'var(--text-secondary)',
              fontSize: 18, padding: 4, lineHeight: 1,
            }}
            aria-label="Evidence panel"
          >
            &#9881;
          </button>
        </div>
      )}

      {/* Main content area */}
      <div style={{
        flex: 1,
        display: 'grid',
        gridTemplateColumns: isMobile ? '1fr'
          : isTablet ? '1fr 360px'
          : '280px 1fr 360px',
        overflow: 'hidden',
        position: 'relative',
      }}>
        {/* Left panel: BookNav (desktop inside grid, tablet slide-over inside grid) */}
        {isTablet && !isMobile ? (
          <>
            {leftOpen && (
              <div
                onClick={() => setLeftOpen(false)}
                style={{
                  position: 'fixed', inset: 0,
                  background: 'rgba(0,0,0,0.5)',
                  zIndex: 30,
                }}
              />
            )}
            <div style={{
              position: 'fixed',
              top: 0, left: 0, bottom: 0,
              width: 320,
              maxWidth: 360,
              transform: leftOpen ? 'translateX(0)' : 'translateX(-100%)',
              transition: 'transform 0.25s ease',
              zIndex: 31,
              background: 'var(--bg-secondary)',
              boxShadow: leftOpen ? '4px 0 20px rgba(0,0,0,0.4)' : 'none',
            }}>
              <BookNav
                epochs={epochs}
                chapters={chapters}
                activeChapterId={activeChapterId}
                onSelectChapter={handleSelectChapter}
                onClose={() => setLeftOpen(false)}
              />
            </div>
          </>
        ) : !isMobile ? (
          <BookNav
            epochs={epochs}
            chapters={chapters}
            activeChapterId={activeChapterId}
            onSelectChapter={handleSelectChapter}
          />
        ) : null}

        {/* Center: NarrativeReader + Audio Player */}
        <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden', minHeight: 0 }}>
          <NarrativeReader
            chapters={chapters}
            activeChapterId={activeChapterId}
            onChapterInView={setActiveChapterId}
            onEntityClick={handleEntityClick}
            onCultureSelect={handleCultureSelect}
            isMobile={isMobile}
          />
          {!isMobile && activeChapterId && (
            <AudioPlayerBar
              chapterId={activeChapterId}
              chapters={chapters}
              onChapterChange={handleAudioChapterChange}
            />
          )}
        </div>

        {/* Right panel: EvidencePanel (desktop/tablet only inside grid) */}
        {!isMobile && (
          <EvidencePanel
            chapter={activeChapter}
            evidence={evidence}
            selectedEntity={selectedEntity}
            onClearEntity={handleClearEntity}
            activeCulture={activeCulture}
          />
        )}
      </div>

      {/* Mobile: audio bar at bottom, outside grid */}
      {isMobile && activeChapterId && (
        <AudioPlayerBar
          chapterId={activeChapterId}
          chapters={chapters}
          onChapterChange={handleAudioChapterChange}
        />
      )}

      {/* Mobile: left nav slide-over, outside grid */}
      {isMobile && (
        <>
          {leftOpen && (
            <div
              onClick={() => setLeftOpen(false)}
              style={{
                position: 'fixed', inset: 0,
                background: 'rgba(0,0,0,0.5)',
                zIndex: 30,
              }}
            />
          )}
          <div style={{
            position: 'fixed',
            top: 0, left: 0, bottom: 0,
            width: '85vw',
            maxWidth: 360,
            transform: leftOpen ? 'translateX(0)' : 'translateX(-100%)',
            transition: 'transform 0.25s ease',
            zIndex: 31,
            background: 'var(--bg-secondary)',
            boxShadow: leftOpen ? '4px 0 20px rgba(0,0,0,0.4)' : 'none',
          }}>
            <BookNav
              epochs={epochs}
              chapters={chapters}
              activeChapterId={activeChapterId}
              onSelectChapter={handleSelectChapter}
              onClose={() => setLeftOpen(false)}
            />
          </div>
        </>
      )}

      {/* Mobile: evidence panel slide-over, outside grid */}
      {isMobile && (
        <>
          {rightOpen && (
            <div
              onClick={() => setRightOpen(false)}
              style={{
                position: 'fixed', inset: 0,
                background: 'rgba(0,0,0,0.5)',
                zIndex: 30,
              }}
            />
          )}
          <div style={{
            position: 'fixed',
            top: 0, right: 0, bottom: 0,
            width: '85vw',
            maxWidth: 400,
            transform: rightOpen ? 'translateX(0)' : 'translateX(100%)',
            transition: 'transform 0.25s ease',
            zIndex: 31,
            background: 'var(--bg-secondary)',
            boxShadow: rightOpen ? '-4px 0 20px rgba(0,0,0,0.4)' : 'none',
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            overflow: 'hidden',
          }}>
            <EvidencePanel
              chapter={activeChapter}
              evidence={evidence}
              selectedEntity={selectedEntity}
              onClearEntity={handleClearEntity}
              activeCulture={activeCulture}
            />
          </div>
        </>
      )}
    </div>
  )
}

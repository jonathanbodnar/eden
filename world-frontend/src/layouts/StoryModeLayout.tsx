import { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import type { StoryChapter, StoryEpoch, StoryEvidence } from '../api'
import BookNav from '../components/story/BookNav'
import NarrativeReader from '../components/story/NarrativeReader'
import EvidencePanel from '../components/story/EvidencePanel'

export default function StoryModeLayout() {
  const [epochs, setEpochs] = useState<StoryEpoch[]>([])
  const [chapters, setChapters] = useState<StoryChapter[]>([])
  const [activeChapterId, setActiveChapterId] = useState<string | null>(null)
  const [evidence, setEvidence] = useState<StoryEvidence[]>([])
  const [selectedEntity, setSelectedEntity] = useState<{
    entityType: string; entityId: string; entityName: string
  } | null>(null)
  const [loading, setLoading] = useState(true)

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
    setSelectedEntity({ entityType, entityId, entityName })
  }, [])

  const handleClearEntity = useCallback(() => {
    setSelectedEntity(null)
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

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '280px 1fr 360px',
      height: '100%',
      overflow: 'hidden',
    }}>
      <BookNav
        epochs={epochs}
        chapters={chapters}
        activeChapterId={activeChapterId}
        onSelectChapter={setActiveChapterId}
      />
      <NarrativeReader
        chapters={chapters}
        activeChapterId={activeChapterId}
        onChapterInView={setActiveChapterId}
        onEntityClick={handleEntityClick}
      />
      <EvidencePanel
        chapter={activeChapter}
        evidence={evidence}
        selectedEntity={selectedEntity}
        onClearEntity={handleClearEntity}
      />
    </div>
  )
}

import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import type {
  ChapterDetail, SourceSet, ContextSet, ArtifactSet, ImageSet, NarrationPacket,
} from '../api'
import { api } from '../api'

interface ChapterState {
  activeChapterId: string | null
  chapterDetail: ChapterDetail | null
  sources: SourceSet[]
  contexts: ContextSet[]
  artifacts: ArtifactSet[]
  images: ImageSet[]
  narration: NarrationPacket | null
  loading: boolean
}

interface ChapterContextValue extends ChapterState {
  selectChapter: (id: string) => Promise<void>
  clearChapter: () => void
}

const ChapterCtx = createContext<ChapterContextValue | null>(null)

export function useChapterContext() {
  const ctx = useContext(ChapterCtx)
  if (!ctx) throw new Error('useChapterContext must be used within ChapterProvider')
  return ctx
}

export function ChapterProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ChapterState>({
    activeChapterId: null,
    chapterDetail: null,
    sources: [],
    contexts: [],
    artifacts: [],
    images: [],
    narration: null,
    loading: false,
  })

  const selectChapter = useCallback(async (id: string) => {
    setState(prev => ({ ...prev, loading: true, activeChapterId: id }))
    try {
      const [detail, sources, contexts, artifacts, images] = await Promise.all([
        api.getChapterDetail(id),
        api.getChapterSources(id),
        api.getChapterContext(id),
        api.getChapterArtifacts(id),
        api.getChapterImages(id),
      ])

      let narration: NarrationPacket | null = null
      try {
        const narrations = await api.getNarration(id)
        if (narrations.length > 0) narration = narrations[0]
      } catch {
        // narration may not exist yet
      }

      setState({
        activeChapterId: id,
        chapterDetail: detail,
        sources,
        contexts,
        artifacts,
        images,
        narration,
        loading: false,
      })
    } catch (err) {
      console.error('Failed to load chapter:', err)
      setState(prev => ({ ...prev, loading: false }))
    }
  }, [])

  const clearChapter = useCallback(() => {
    setState({
      activeChapterId: null,
      chapterDetail: null,
      sources: [],
      contexts: [],
      artifacts: [],
      images: [],
      narration: null,
      loading: false,
    })
  }, [])

  return (
    <ChapterCtx.Provider value={{ ...state, selectChapter, clearChapter }}>
      {children}
    </ChapterCtx.Provider>
  )
}

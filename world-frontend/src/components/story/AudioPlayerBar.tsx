import { useState, useRef, useEffect, useCallback } from 'react'
import type { StoryChapter } from '../../api'

const BASE = '/world-api'

interface Props {
  chapterId: string
  chapters: StoryChapter[]
  onChapterChange: (chapterId: string) => void
  onClose: () => void
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

const SPEEDS = [0.75, 1, 1.25, 1.5]

export default function AudioPlayerBar({ chapterId, chapters, onChapterChange, onClose }: Props) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [speed, setSpeed] = useState(1)
  const [error, setError] = useState<string | null>(null)
  const [audioSrc, setAudioSrc] = useState<string | null>(null)

  const chapter = chapters.find(c => c.id === chapterId)
  const chapterIdx = chapters.findIndex(c => c.id === chapterId)

  const loadAudio = useCallback(async (id: string) => {
    setLoading(true)
    setError(null)
    setGenerating(false)
    setCurrentTime(0)
    setDuration(0)
    setPlaying(false)

    try {
      const checkRes = await fetch(`${BASE}/story/chapters/${id}/audio`, { method: 'HEAD' })
      if (checkRes.ok) {
        setAudioSrc(`${BASE}/story/chapters/${id}/audio`)
        setLoading(false)
        return
      }

      setGenerating(true)
      const genRes = await fetch(`${BASE}/story/chapters/${id}/audio`, { method: 'POST' })
      if (!genRes.ok) {
        const errText = await genRes.text()
        throw new Error(errText || `Generation failed (${genRes.status})`)
      }

      const genData = await genRes.json()
      if (genData.status === 'already_exists') {
        setAudioSrc(`${BASE}/story/chapters/${id}/audio?t=${Date.now()}`)
        setLoading(false)
        setGenerating(false)
        return
      }

      if (genData.status === 'generating') {
        let attempts = 0
        const maxAttempts = 120
        while (attempts < maxAttempts) {
          await new Promise(r => setTimeout(r, 3000))
          attempts++
          const pollRes = await fetch(`${BASE}/story/chapters/${id}/audio`, { method: 'HEAD' })
          if (pollRes.ok) {
            setAudioSrc(`${BASE}/story/chapters/${id}/audio?t=${Date.now()}`)
            setLoading(false)
            setGenerating(false)
            return
          }
          const retryGen = await fetch(`${BASE}/story/chapters/${id}/audio`, { method: 'POST' })
          if (retryGen.ok) {
            const retryData = await retryGen.json()
            if (retryData.status === 'already_exists') {
              setAudioSrc(`${BASE}/story/chapters/${id}/audio?t=${Date.now()}`)
              setLoading(false)
              setGenerating(false)
              return
            }
            if (retryData.status !== 'generating') break
          } else {
            const errText = await retryGen.text()
            throw new Error(errText || `Generation failed (${retryGen.status})`)
          }
        }
        if (attempts >= maxAttempts) {
          throw new Error('Audio generation timed out')
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audio')
    } finally {
      setLoading(false)
      setGenerating(false)
    }
  }, [])

  useEffect(() => {
    loadAudio(chapterId)
  }, [chapterId, loadAudio])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !audioSrc) return

    audio.src = audioSrc
    audio.playbackRate = speed
    audio.load()

    const onLoaded = () => {
      setDuration(audio.duration)
      audio.play().then(() => setPlaying(true)).catch(() => {})
    }
    const onTimeUpdate = () => setCurrentTime(audio.currentTime)
    const onEnded = () => {
      setPlaying(false)
      if (chapterIdx < chapters.length - 1) {
        onChapterChange(chapters[chapterIdx + 1].id)
      }
    }
    const onError = () => setError('Audio playback error')

    audio.addEventListener('loadedmetadata', onLoaded)
    audio.addEventListener('timeupdate', onTimeUpdate)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('error', onError)

    return () => {
      audio.removeEventListener('loadedmetadata', onLoaded)
      audio.removeEventListener('timeupdate', onTimeUpdate)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('error', onError)
    }
  }, [audioSrc, chapterIdx, chapters, onChapterChange, speed])

  const togglePlay = () => {
    const audio = audioRef.current
    if (!audio) return
    if (playing) {
      audio.pause()
      setPlaying(false)
    } else {
      audio.play().then(() => setPlaying(true)).catch(() => {})
    }
  }

  const seek = (e: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current
    if (!audio || !duration) return
    const rect = e.currentTarget.getBoundingClientRect()
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    audio.currentTime = pct * duration
    setCurrentTime(audio.currentTime)
  }

  const cycleSpeed = () => {
    const idx = SPEEDS.indexOf(speed)
    const next = SPEEDS[(idx + 1) % SPEEDS.length]
    setSpeed(next)
    if (audioRef.current) audioRef.current.playbackRate = next
  }

  const skipPrev = () => {
    if (currentTime > 5 && audioRef.current) {
      audioRef.current.currentTime = 0
      setCurrentTime(0)
    } else if (chapterIdx > 0) {
      onChapterChange(chapters[chapterIdx - 1].id)
    }
  }

  const skipNext = () => {
    if (chapterIdx < chapters.length - 1) {
      onChapterChange(chapters[chapterIdx + 1].id)
    }
  }

  const progress = duration > 0 ? (currentTime / duration) * 100 : 0

  return (
    <div style={{
      height: 72,
      flexShrink: 0,
      background: 'var(--bg-secondary)',
      borderTop: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      zIndex: 20,
    }}>
      <audio ref={audioRef} preload="metadata" />

      {/* Progress bar */}
      <div
        onClick={seek}
        style={{
          height: 4,
          background: 'var(--bg-tertiary)',
          cursor: duration > 0 ? 'pointer' : 'default',
          flexShrink: 0,
        }}
      >
        <div style={{
          height: '100%',
          width: `${progress}%`,
          background: 'var(--gold)',
          transition: 'width 0.1s linear',
        }} />
      </div>

      {/* Controls row */}
      <div style={{
        flex: 1,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '0 12px',
      }}>
        {/* Chapter info */}
        <div style={{
          flex: 1,
          minWidth: 0,
          overflow: 'hidden',
        }}>
          <div style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--text-primary)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {chapter?.chapter_title || 'Loading...'}
          </div>
          <div style={{ fontSize: 11, color: generating ? 'var(--gold)' : 'var(--text-muted)' }}>
            {loading || generating
              ? (generating ? 'Generating audio \u2014 this is cached for all listeners...' : 'Loading...')
              : error
                ? error
                : `${formatTime(currentTime)} / ${formatTime(duration)}`
            }
          </div>
        </div>

        {/* Transport controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <button
            onClick={skipPrev}
            disabled={chapterIdx <= 0 && currentTime <= 5}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--text-secondary)', fontSize: 16, padding: 6,
              opacity: (chapterIdx <= 0 && currentTime <= 5) ? 0.3 : 1,
            }}
          >
            &#9664;&#9664;
          </button>

          <button
            onClick={togglePlay}
            disabled={loading || !!error}
            style={{
              background: 'var(--gold)',
              border: 'none',
              borderRadius: '50%',
              width: 40,
              height: 40,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: loading || error ? 'default' : 'pointer',
              color: 'var(--bg-primary)',
              fontSize: 16,
              opacity: loading ? 0.5 : 1,
            }}
          >
            {loading || generating ? (
              <span style={{ animation: 'pulse 1.2s ease-in-out infinite' }}>&#9679;</span>
            ) : playing ? (
              <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: 2 }}>&#9646;&#9646;</span>
            ) : (
              <span style={{ marginLeft: 2 }}>&#9654;</span>
            )}
          </button>

          <button
            onClick={skipNext}
            disabled={chapterIdx >= chapters.length - 1}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--text-secondary)', fontSize: 16, padding: 6,
              opacity: chapterIdx >= chapters.length - 1 ? 0.3 : 1,
            }}
          >
            &#9654;&#9654;
          </button>
        </div>

        {/* Speed control */}
        <button
          onClick={cycleSpeed}
          style={{
            background: 'var(--bg-tertiary)',
            border: '1px solid var(--border)',
            borderRadius: 12,
            padding: '3px 8px',
            fontSize: 11,
            fontWeight: 600,
            color: speed === 1 ? 'var(--text-muted)' : 'var(--gold)',
            cursor: 'pointer',
            whiteSpace: 'nowrap',
          }}
        >
          {speed}x
        </button>

        {/* Close */}
        <button
          onClick={onClose}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--text-muted)', fontSize: 18, padding: 4,
          }}
        >
          &times;
        </button>
      </div>
    </div>
  )
}

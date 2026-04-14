import { useEffect, useState, useMemo } from 'react'
import type { Chapter } from '../../api'
import { api } from '../../api'
import ChapterItem from './ChapterItem'

function formatYear(y: number | null): string {
  if (y === null) return '?'
  if (y < 0) return `${Math.abs(y)} BCE`
  return `${y} CE`
}

const PAGE_SIZE = 30

export default function ChapterList({ epochId }: { epochId: string }) {
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE)

  useEffect(() => {
    setSearch('')
    setVisibleCount(PAGE_SIZE)
    api.getChapters(epochId)
      .then(setChapters)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [epochId])

  const filtered = useMemo(() => {
    if (!search.trim()) return chapters
    const q = search.toLowerCase()
    return chapters.filter(c =>
      c.title.toLowerCase().includes(q) ||
      (c.time_start !== null && formatYear(c.time_start).toLowerCase().includes(q))
    )
  }, [chapters, search])

  const visible = filtered.slice(0, visibleCount)
  const remaining = filtered.length - visibleCount

  if (loading) {
    return (
      <div style={{ padding: '6px 14px 8px 24px', color: 'var(--text-muted)', fontSize: '11px' }}>
        Loading...
      </div>
    )
  }

  if (chapters.length === 0) {
    return (
      <div style={{ padding: '6px 14px 8px 24px', color: 'var(--text-muted)', fontSize: '11px' }}>
        No chapters
      </div>
    )
  }

  return (
    <div style={{ paddingBottom: '2px' }}>
      {chapters.length > 10 && (
        <div style={{ padding: '4px 14px 4px 20px' }}>
          <input
            type="text"
            placeholder={`Filter ${chapters.length} chapters...`}
            value={search}
            onChange={e => { setSearch(e.target.value); setVisibleCount(PAGE_SIZE) }}
            style={{
              width: '100%',
              padding: '5px 8px',
              fontSize: '10px',
              background: 'var(--bg-primary)',
              border: '1px solid var(--border)',
              borderRadius: '4px',
              color: 'var(--text-primary)',
              outline: 'none',
            }}
          />
        </div>
      )}
      {visible.map(chapter => (
        <ChapterItem key={chapter.id} chapter={chapter} />
      ))}
      {remaining > 0 && (
        <div
          onClick={() => setVisibleCount(prev => prev + PAGE_SIZE)}
          style={{
            padding: '6px 14px 8px 24px',
            color: 'var(--accent)',
            fontSize: '10px',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          Show more ({remaining} remaining)
        </div>
      )}
    </div>
  )
}

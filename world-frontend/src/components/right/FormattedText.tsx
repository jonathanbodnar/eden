import type { ReactNode } from 'react'

export default function FormattedText({ text }: { text: string }) {
  const paragraphs = text.split(/\n\n+/)

  return (
    <div>
      {paragraphs.map((para, i) => (
        <p key={i} style={{ margin: i > 0 ? '10px 0 0' : '0' }}>
          {renderInline(para)}
        </p>
      ))}
    </div>
  )
}

function renderInline(text: string): (string | ReactNode)[] {
  const parts: (string | ReactNode)[] = []
  let keyIdx = 0

  const regex = /(\*\*(.+?)\*\*)|(\*(.+?)\*)|("([^"]+?)")|(\n)/g
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index))
    }

    if (match[1]) {
      parts.push(
        <strong key={keyIdx++} style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
          {match[2]}
        </strong>
      )
    } else if (match[3]) {
      parts.push(
        <em key={keyIdx++} style={{ fontStyle: 'italic', color: 'var(--text-secondary)' }}>
          {match[4]}
        </em>
      )
    } else if (match[5]) {
      parts.push(
        <span key={keyIdx++} style={{
          color: 'var(--accent-hover)',
          fontStyle: 'italic',
        }}>
          &ldquo;{match[6]}&rdquo;
        </span>
      )
    } else if (match[7]) {
      parts.push(<br key={keyIdx++} />)
    }

    lastIndex = match.index + match[0].length
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex))
  }

  return parts
}

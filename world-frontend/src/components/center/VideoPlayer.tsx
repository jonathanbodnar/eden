import { useState } from 'react'
import { useWorldContext } from '../../context/WorldContext'
import type { VideoScene } from '../../api'

export default function VideoPlayer() {
  const ctx = useWorldContext()
  const ctxAny = ctx as unknown as Record<string, unknown>
  const activeVideo = ctxAny.chapterVideo as import('../../api').VideoStatus | null
  const videoLoading = ctxAny.videoLoading as boolean | undefined
  const [expandedScene, setExpandedScene] = useState<number | null>(null)
  const [showAllScenes, setShowAllScenes] = useState(false)

  if (videoLoading && !activeVideo) {
    return (
      <div style={{
        background: 'linear-gradient(135deg, rgba(0,0,0,0.85), rgba(15,15,30,0.9))',
        borderRadius: '10px',
        padding: '24px',
        marginBottom: '16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '120px',
        border: '1px solid var(--border)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '20px', height: '20px',
            border: '2px solid var(--border)',
            borderTopColor: 'var(--accent)',
            borderRadius: '50%',
            animation: 'pulse 1s infinite',
          }} />
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>Loading video...</span>
        </div>
      </div>
    )
  }

  if (!activeVideo) return null

  if (activeVideo.has_video && activeVideo.video?.r2_key) {
    return (
      <div style={{
        marginBottom: '16px',
        borderRadius: '10px',
        overflow: 'hidden',
        border: '1px solid var(--border)',
        background: '#000',
        animation: 'fadeIn 0.4s',
      }}>
        <video
          controls
          preload="metadata"
          style={{ width: '100%', maxHeight: '360px', display: 'block' }}
          poster={activeVideo.video.thumbnail_r2_key || undefined}
        >
          <source src={activeVideo.video.r2_key} type="video/mp4" />
        </video>
        <div style={{
          padding: '8px 12px',
          background: 'var(--bg-tertiary)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
            {activeVideo.video.video_type.replace(/_/g, ' ')}
            {activeVideo.video.duration_seconds && ` · ${Math.floor(activeVideo.video.duration_seconds / 60)}:${(activeVideo.video.duration_seconds % 60).toString().padStart(2, '0')}`}
          </span>
          <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
            v{activeVideo.video.version}
          </span>
        </div>
      </div>
    )
  }

  if (activeVideo.has_script && activeVideo.script) {
    const scenes = activeVideo.script.scenes_json || []
    const totalDuration = scenes.reduce((s: number, sc: VideoScene) => s + (sc.duration_estimate_seconds || 0), 0)
    const visibleScenes = showAllScenes ? scenes : scenes.slice(0, 4)

    return (
      <div style={{
        marginBottom: '16px',
        background: 'linear-gradient(135deg, rgba(0,0,0,0.7), rgba(15,15,30,0.85))',
        border: '1px solid var(--border)',
        borderRadius: '10px',
        overflow: 'hidden',
        animation: 'fadeIn 0.3s',
      }}>
        <div style={{
          padding: '14px 16px 10px',
          background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.1), rgba(212, 168, 83, 0.06))',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <div style={{
                fontSize: '9px',
                fontWeight: 600,
                color: 'var(--accent)',
                textTransform: 'uppercase',
                letterSpacing: '0.1em',
                marginBottom: '4px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}>
                <span style={{
                  display: 'inline-block',
                  width: '6px', height: '6px',
                  borderRadius: '50%',
                  background: 'var(--accent)',
                  animation: 'pulse 2s infinite',
                }} />
                Script Generated · {scenes.length} Scenes
              </div>
              {activeVideo.script.title && (
                <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1.3 }}>
                  {activeVideo.script.title}
                </div>
              )}
            </div>
            <div style={{ textAlign: 'right', flexShrink: 0 }}>
              <div style={{ fontSize: '18px', fontWeight: 700, color: 'var(--gold)' }}>
                {Math.floor(totalDuration / 60)}:{(totalDuration % 60).toString().padStart(2, '0')}
              </div>
              <div style={{ fontSize: '9px', color: 'var(--text-muted)', marginTop: '1px' }}>
                estimated runtime
              </div>
            </div>
          </div>
        </div>

        <div style={{ padding: '8px 10px' }}>
          {visibleScenes.map((scene: VideoScene, i: number) => {
            const isExpanded = expandedScene === i
            return (
              <div
                key={i}
                onClick={() => setExpandedScene(isExpanded ? null : i)}
                style={{
                  padding: '8px 10px',
                  marginBottom: '4px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  background: isExpanded ? 'rgba(99, 102, 241, 0.08)' : 'transparent',
                  border: `1px solid ${isExpanded ? 'rgba(99, 102, 241, 0.2)' : 'transparent'}`,
                  transition: 'all 0.2s ease',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span style={{
                    fontSize: '9px',
                    fontWeight: 700,
                    color: 'var(--accent)',
                    background: 'rgba(99, 102, 241, 0.12)',
                    padding: '2px 5px',
                    borderRadius: '3px',
                    minWidth: '20px',
                    textAlign: 'center',
                  }}>{i + 1}</span>
                  <span style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-primary)', flex: 1 }}>
                    {scene.name}
                  </span>
                  <span style={{
                    fontSize: '9px',
                    color: 'var(--gold)',
                    background: 'rgba(212, 168, 83, 0.1)',
                    padding: '1px 5px',
                    borderRadius: '3px',
                    fontStyle: 'italic',
                  }}>{scene.tone}</span>
                  <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
                    {scene.duration_estimate_seconds}s
                  </span>
                  <span style={{
                    fontSize: '10px',
                    color: 'var(--text-muted)',
                    transform: isExpanded ? 'rotate(180deg)' : 'rotate(0)',
                    transition: 'transform 0.2s',
                  }}>▾</span>
                </div>

                {isExpanded && (
                  <div style={{ marginTop: '10px', paddingLeft: '28px', animation: 'fadeIn 0.2s' }}>
                    {scene.narration && (
                      <div style={{
                        fontSize: '12px',
                        color: 'var(--text-secondary)',
                        lineHeight: 1.7,
                        whiteSpace: 'pre-line',
                        borderLeft: '2px solid var(--accent)',
                        paddingLeft: '12px',
                        marginBottom: '8px',
                      }}>
                        {scene.narration}
                      </div>
                    )}
                    {scene.visual_prompt && (
                      <div style={{
                        fontSize: '10px',
                        color: 'var(--text-muted)',
                        fontStyle: 'italic',
                        marginTop: '6px',
                        padding: '6px 8px',
                        background: 'rgba(212, 168, 83, 0.06)',
                        borderRadius: '4px',
                        border: '1px solid rgba(212, 168, 83, 0.1)',
                      }}>
                        <span style={{ color: 'var(--gold)', fontWeight: 600 }}>Visual:</span> {scene.visual_prompt}
                      </div>
                    )}
                    {scene.actors && scene.actors.length > 0 && (
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '4px' }}>
                        <span style={{ fontWeight: 600 }}>Actors:</span> {scene.actors.join(', ')}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}

          {scenes.length > 4 && (
            <div
              onClick={() => setShowAllScenes(!showAllScenes)}
              style={{
                textAlign: 'center',
                padding: '6px',
                cursor: 'pointer',
                fontSize: '10px',
                color: 'var(--accent)',
                fontWeight: 600,
              }}
            >
              {showAllScenes ? 'Show less' : `Show all ${scenes.length} scenes`}
            </div>
          )}
        </div>

        <div style={{
          padding: '6px 16px 8px',
          borderTop: '1px solid rgba(255,255,255,0.04)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
            Awaiting visual + audio generation
          </span>
          <span style={{ fontSize: '9px', color: 'var(--text-muted)' }}>
            v{activeVideo.script.version}
          </span>
        </div>
      </div>
    )
  }

  return null
}

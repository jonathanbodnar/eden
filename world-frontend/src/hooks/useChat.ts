import { useState, useCallback } from 'react'
import type { ChatQueryResult, ChatMessage, AnswerSource, AnswerContext } from '../api'
import { api } from '../api'

interface ChatState {
  sessionId: string | null
  messages: ChatMessage[]
  loading: boolean
  lastAnswer: ChatQueryResult | null
  answerSources: AnswerSource[]
  answerContexts: AnswerContext[]
}

export function useChat(chapterId: string | null) {
  const [state, setState] = useState<ChatState>({
    sessionId: null,
    messages: [],
    loading: false,
    lastAnswer: null,
    answerSources: [],
    answerContexts: [],
  })

  const sendMessage = useCallback(async (query: string) => {
    setState(prev => ({
      ...prev,
      loading: true,
      messages: [...prev.messages, {
        id: crypto.randomUUID(),
        session_id: prev.sessionId || '',
        role: 'user',
        content: query,
        answer_packet_id: null,
        created_at: new Date().toISOString(),
      }],
    }))

    try {
      const result = await api.chatQuery(query, chapterId || undefined, state.sessionId || undefined)

      setState(prev => ({
        ...prev,
        sessionId: result.session_id,
        loading: false,
        lastAnswer: result,
        answerSources: result.sources,
        answerContexts: result.contexts,
        messages: [...prev.messages, {
          id: crypto.randomUUID(),
          session_id: result.session_id,
          role: 'assistant',
          content: result.answer,
          answer_packet_id: result.answer_packet_id,
          created_at: new Date().toISOString(),
        }],
      }))

      return result
    } catch (err) {
      console.error('Chat query failed:', err)
      setState(prev => ({
        ...prev,
        loading: false,
        messages: [...prev.messages, {
          id: crypto.randomUUID(),
          session_id: prev.sessionId || '',
          role: 'assistant',
          content: 'An error occurred. Please try again.',
          answer_packet_id: null,
          created_at: new Date().toISOString(),
        }],
      }))
      return null
    }
  }, [chapterId, state.sessionId])

  const resetChat = useCallback(() => {
    setState({
      sessionId: null,
      messages: [],
      loading: false,
      lastAnswer: null,
      answerSources: [],
      answerContexts: [],
    })
  }, [])

  return { ...state, sendMessage, resetChat }
}

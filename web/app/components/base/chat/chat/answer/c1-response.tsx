'use client'

import type {
  ComponentProps,
  FC,
} from 'react'
import { cn } from '@langgenius/dify-ui/cn'
import { C1Component, ThemeProvider } from '@thesysai/genui-sdk'
import { useTheme } from 'next-themes'
import { useEffect, useRef, useState } from 'react'
import { useChatContext } from '../context'
import './c1-response.css'

type C1Action = Parameters<NonNullable<ComponentProps<typeof C1Component>['onAction']>>[0]

type C1ResponseProps = {
  content: string
  className?: string
  dataTestId: string
  responding?: boolean
}

// Only allow absolute http(s) navigation from C1 actions. LLM output is
// untrusted, so we must reject javascript:, data:, file:, relative paths, and
// anything without an explicit scheme. Parsing without a base makes `new URL`
// throw on relative/no-scheme inputs, which we treat as unsafe.
const isSafeExternalUrl = (raw: string): boolean => {
  try {
    const parsed = new URL(raw)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  }
  catch {
    return false
  }
}

// The SDK renders a red "Error while generating response" message whenever
// `isStreaming` is false AND its internal validator has not yet produced a
// parsed component tree. When `responding` flips to false, the validator may
// take a render tick to settle, which paints that error state for one frame.
// Keep `isStreaming` latched to true briefly after the stream actually ends so
// the SDK stays silent through that transition.
const SETTLE_DELAY_MS = 400

const useSettledIsStreaming = (responding: boolean | undefined): boolean => {
  const [latched, setLatched] = useState<boolean>(!!responding)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // This effect intentionally drives a latch off a prop change plus a timer.
  // The sync `setLatched(true)` path below is the only way to re-latch when
  // the parent flips `responding` back to true while we're still in the
  // settle window; React's render-phase bail-out avoids an extra render when
  // the state is already true.
  useEffect(() => {
    if (responding) {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
      // eslint-disable-next-line react/set-state-in-effect
      setLatched(true)
      return
    }
    timerRef.current = setTimeout(() => {
      setLatched(false)
      timerRef.current = null
    }, SETTLE_DELAY_MS)

    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current)
        timerRef.current = null
      }
    }
  }, [responding])

  return latched
}

const C1Response: FC<C1ResponseProps> = ({
  content,
  className,
  dataTestId,
  responding,
}) => {
  const { onSend, readonly } = useChatContext()
  const isStreaming = useSettledIsStreaming(responding)
  // Mirror Dify's light/dark theme into the SDK so a dark chat shell doesn't
  // paint a glaring light-mode generative UI inside it. `resolvedTheme`
  // collapses `system` into the actual `light` / `dark` value.
  const { resolvedTheme } = useTheme()
  const c1Mode: 'light' | 'dark' = resolvedTheme === 'dark' ? 'dark' : 'light'

  const handleAction = (event: C1Action) => {
    if (event.type === 'open_url') {
      const url = typeof event.params?.url === 'string' ? event.params.url : undefined
      if (url && isSafeExternalUrl(url))
        window.open(url, '_blank', 'noopener,noreferrer')

      return
    }

    if (readonly)
      return

    const llmFriendlyMessage = typeof event.params?.llmFriendlyMessage === 'string'
      ? event.params.llmFriendlyMessage
      : event.llmFriendlyMessage
    const humanFriendlyMessage = typeof event.params?.humanFriendlyMessage === 'string'
      ? event.params.humanFriendlyMessage
      : event.humanFriendlyMessage

    const nextMessage = llmFriendlyMessage || humanFriendlyMessage
    if (nextMessage)
      onSend?.(nextMessage)
  }

  return (
    <div
      // `container-type: inline-size` is what lets the SDK's internal
      // responsive rules (`@container (max-width: …)`) fire against the
      // chat-bubble width. Without it, grids of charts / cards render at
      // their "has room" layout and overlap inside narrow bubbles.
      className={cn('dify-c1-content @container text-text-primary', className)}
      style={{ containerType: 'inline-size' }}
      data-testid={dataTestId}
    >
      <ThemeProvider mode={c1Mode}>
        <C1Component
          c1Response={content}
          isStreaming={isStreaming}
          onAction={handleAction}
        />
      </ThemeProvider>
    </div>
  )
}

export default C1Response

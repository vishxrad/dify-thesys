'use client'

import type {
  ComponentProps,
  FC,
} from 'react'
import { C1Component, ThemeProvider } from '@thesysai/genui-sdk'
import { useChatContext } from '../context'

type C1Action = Parameters<NonNullable<ComponentProps<typeof C1Component>['onAction']>>[0]

type C1ResponseProps = {
  content: string
  className?: string
  dataTestId: string
  responding?: boolean
}

const C1Response: FC<C1ResponseProps> = ({
  content,
  className,
  dataTestId,
  responding,
}) => {
  const { onSend, readonly } = useChatContext()

  const handleAction = (event: C1Action) => {
    if (event.type === 'open_url') {
      const url = typeof event.params?.url === 'string' ? event.params.url : undefined
      if (url)
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
      className={className ? `text-text-primary ${className}` : 'text-text-primary'}
      data-testid={dataTestId}
    >
      <ThemeProvider>
        <C1Component
          c1Response={content}
          isStreaming={!!responding}
          onAction={handleAction}
        />
      </ThemeProvider>
    </div>
  )
}

export default C1Response

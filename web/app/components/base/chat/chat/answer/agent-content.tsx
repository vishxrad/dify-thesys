import type { FC } from 'react'
import type {
  ChatItem,
} from '../../types'
import { memo } from 'react'
import Thought from '@/app/components/base/chat/chat/thought'
import { FileList } from '@/app/components/base/file-uploader'
import { getProcessedFilesFromResponse } from '@/app/components/base/file-uploader/utils'
import { Markdown } from '@/app/components/base/markdown'
import ResponseRenderer from './response-renderer'

type AgentContentProps = {
  item: ChatItem
  responding?: boolean
  content?: string
}
const AgentContent: FC<AgentContentProps> = ({
  item,
  responding,
  content,
}) => {
  const {
    annotation,
    agent_thoughts,
  } = item

  // Annotations are user-authored edits; always render them as Markdown so an
  // annotation that happens to start with a C1-looking tag does not get handed
  // to the generative-UI renderer.
  if (annotation?.logAnnotation) {
    return (
      <div data-testid="agent-content-markdown">
        <Markdown content={annotation.logAnnotation.content ?? ''} />
      </div>
    )
  }

  return (
    <div data-testid="agent-content-container">
      {content
        ? (
            <ResponseRenderer
              content={content}
              responding={responding}
              testIdBase="agent-content"
            />
          )
        : agent_thoughts?.map(thought => (
            <div key={thought.id} className="px-2 py-1" data-testid="agent-thought-item">
              {thought.thought && (
                <Markdown
                  content={thought.thought}
                  data-testid="agent-thought-markdown"
                />
              )}
              {!!thought.tool && (
                <Thought
                  thought={thought}
                  isFinished={!!thought.observation || !responding}
                />
              )}

              {
                !!thought.message_files?.length && (
                  <FileList
                    files={getProcessedFilesFromResponse(thought.message_files.map(file => ({ ...file, related_id: file.id })))}
                    showDeleteAction={false}
                    showDownloadAction={true}
                    canPreview={true}
                  />
                )
              }
            </div>
          ))}
    </div>
  )
}

export default memo(AgentContent)

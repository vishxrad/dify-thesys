import type { FC } from 'react'
import type { ChatItem } from '../../types'
import { memo } from 'react'
import { Markdown } from '@/app/components/base/markdown'
import ResponseRenderer from './response-renderer'

type BasicContentProps = {
  item: ChatItem
}

// Preserve Windows UNC paths and similar backslash-heavy strings by wrapping
// them in inline code so Markdown renders backslashes verbatim.
const wrapUncPath = (content: string): string => {
  if (/^\\\\\S.*/.test(content) && !/^`.*`$/.test(content))
    return `\`${content}\``
  return content
}

const BasicContent: FC<BasicContentProps> = ({
  item,
}) => {
  const {
    annotation,
    content,
  } = item

  // Annotations are user-authored edits; always render them as Markdown so an
  // annotation that happens to start with a C1-looking tag does not get handed
  // to the generative-UI renderer.
  if (annotation?.logAnnotation) {
    return (
      <div data-testid="basic-content-markdown">
        <Markdown content={annotation.logAnnotation.content ?? ''} />
      </div>
    )
  }

  return (
    <ResponseRenderer
      className={item.isError ? 'text-[#F04438]!' : undefined}
      content={wrapUncPath(content)}
      testIdBase="basic-content"
    />
  )
}

export default memo(BasicContent)

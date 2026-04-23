import type { FC } from 'react'
import type { ChatItem } from '../../types'
import { memo } from 'react'
import ResponseRenderer from './response-renderer'

type BasicContentProps = {
  item: ChatItem
}
const BasicContent: FC<BasicContentProps> = ({
  item,
}) => {
  const {
    annotation,
    content,
  } = item

  if (annotation?.logAnnotation) {
    return (
      <ResponseRenderer
        content={annotation.logAnnotation.content ?? ''}
        testIdBase="basic-content"
      />
    )
  }

  // Preserve Windows UNC paths and similar backslash-heavy strings by
  // wrapping them in inline code so Markdown renders backslashes verbatim.
  let displayContent = content
  if (/^\\\\\S.*/.test(content) && !/^`.*`$/.test(content)) {
    displayContent = `\`${content}\``
  }

  return (
    <ResponseRenderer
      className={item.isError ? 'text-[#F04438]!' : undefined}
      content={displayContent}
      testIdBase="basic-content"
    />
  )
}

export default memo(BasicContent)

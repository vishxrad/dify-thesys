import type { FC } from 'react'
import { Markdown } from '@/app/components/base/markdown'
import dynamic from '@/next/dynamic'
import { detectResponseFormat } from './detect-response-format'

const C1Response = dynamic(() => import('./c1-response'), {
  ssr: false,
})

type ResponseRendererProps = {
  content: string
  className?: string
  responding?: boolean
  testIdBase: string
}

const ResponseRenderer: FC<ResponseRendererProps> = ({
  content,
  className,
  responding,
  testIdBase,
}) => {
  if (detectResponseFormat(content) === 'c1') {
    return (
      <C1Response
        className={className}
        content={content}
        dataTestId={`${testIdBase}-c1`}
        responding={responding}
      />
    )
  }

  return (
    <Markdown
      className={className}
      content={content}
      data-testid={`${testIdBase}-markdown`}
    />
  )
}

export default ResponseRenderer

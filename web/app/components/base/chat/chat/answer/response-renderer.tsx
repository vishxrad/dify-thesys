import type { FC } from 'react'
import { Markdown } from '@/app/components/base/markdown'
import ErrorBoundary from '@/app/components/base/markdown/error-boundary'
import dynamic from '@/next/dynamic'
import { detectResponseFormat } from './detect-response-format'

const C1Response = dynamic(() => import('./c1-response'), {
  ssr: false,
})

// Warm the C1 chunk at module init so the first transition from Markdown to C1
// does not flash blank while Next fetches the lazy bundle in the browser.
if (typeof window !== 'undefined')
  void import('./c1-response')

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
  const format = detectResponseFormat(content, { stable: !responding })

  if (format === 'c1') {
    return (
      <ErrorBoundary>
        <C1Response
          className={className}
          content={content}
          dataTestId={`${testIdBase}-c1`}
          responding={responding}
        />
      </ErrorBoundary>
    )
  }

  return (
    <div data-testid={`${testIdBase}-markdown`}>
      <Markdown
        className={className}
        content={content}
      />
    </div>
  )
}

export default ResponseRenderer

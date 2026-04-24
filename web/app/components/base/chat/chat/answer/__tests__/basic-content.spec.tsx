import type { ReactNode } from 'react'
import type { ChatItem } from '../../../types'
import type { MarkdownProps } from '@/app/components/base/markdown'
import { render, screen, within } from '@testing-library/react'
import BasicContent from '../basic-content'

vi.mock('@thesysai/genui-sdk', () => ({
  ThemeProvider: ({ children }: { children: ReactNode }) => children,
  C1Component: ({ c1Response }: { c1Response: string }) => (
    <div data-testid="c1-component" data-response={c1Response}>
      {c1Response}
    </div>
  ),
}))

// The real `Markdown` component renders a `<div data-testid="markdown-body">`,
// so the `basic-content-markdown` testid is owned by the BasicContent wrapper.
// Reflect that here: the mocked Markdown only carries data we assert against.
vi.mock('@/app/components/base/markdown', () => ({
  Markdown: ({ content, className }: MarkdownProps) => (
    <div data-testid="markdown-mock" data-content={String(content)} className={className}>
      {String(content)}
    </div>
  ),
}))

describe('BasicContent', () => {
  const mockItem = {
    id: '1',
    content: 'Hello World',
    isAnswer: true,
  }

  const getMarkdownContent = () =>
    within(screen.getByTestId('basic-content-markdown')).getByTestId('markdown-mock')

  it('renders content correctly', () => {
    render(<BasicContent item={mockItem as ChatItem} />)
    expect(getMarkdownContent()).toHaveAttribute('data-content', 'Hello World')
  })

  it('renders logAnnotation content if present', () => {
    const itemWithAnnotation = {
      ...mockItem,
      annotation: {
        logAnnotation: {
          content: 'Annotated Content',
        },
      },
    }
    render(<BasicContent item={itemWithAnnotation as ChatItem} />)
    expect(getMarkdownContent()).toHaveAttribute('data-content', 'Annotated Content')
  })

  it('renders annotation content as plain Markdown even when it looks like C1', () => {
    const itemWithC1LookingAnnotation = {
      ...mockItem,
      annotation: {
        logAnnotation: {
          content: '<content><Card title="From annotation" /></content>',
        },
      },
    }
    render(<BasicContent item={itemWithC1LookingAnnotation as ChatItem} />)

    expect(screen.queryByTestId('basic-content-c1')).not.toBeInTheDocument()
    expect(screen.queryByTestId('c1-component')).not.toBeInTheDocument()
    expect(getMarkdownContent()).toHaveAttribute('data-content', '<content><Card title="From annotation" /></content>')
  })

  it('renders C1 responses with the C1 renderer', () => {
    const itemWithC1Content = {
      ...mockItem,
      content: '<content><Card title="Hello" /></content>',
    }

    render(<BasicContent item={itemWithC1Content as ChatItem} />)

    expect(screen.getByTestId('basic-content-c1')).toBeInTheDocument()
    expect(screen.getByTestId('c1-component')).toHaveAttribute('data-response', '<content><Card title="Hello" /></content>')
  })

  it('renders empty string if logAnnotation content is missing', () => {
    const itemWithEmptyAnnotation = {
      ...mockItem,
      annotation: {
        logAnnotation: {
          content: '',
        },
      },
    }
    const { rerender } = render(<BasicContent item={itemWithEmptyAnnotation as ChatItem} />)
    expect(getMarkdownContent()).toHaveAttribute('data-content', '')

    const itemWithUndefinedAnnotation = {
      ...mockItem,
      annotation: {
        logAnnotation: {},
      },
    }
    rerender(<BasicContent item={itemWithUndefinedAnnotation as ChatItem} />)
    expect(getMarkdownContent()).toHaveAttribute('data-content', '')
  })

  it('wraps Windows UNC paths in backticks', () => {
    const itemWithUNC = {
      ...mockItem,
      content: '\\\\server\\share\\file.txt',
    }
    render(<BasicContent item={itemWithUNC as ChatItem} />)
    expect(getMarkdownContent()).toHaveAttribute('data-content', '`\\\\server\\share\\file.txt`')
  })

  it('does not wrap content in backticks if it already is', () => {
    const itemWithBackticks = {
      ...mockItem,
      content: '`\\\\server\\share\\file.txt`',
    }
    render(<BasicContent item={itemWithBackticks as ChatItem} />)
    expect(getMarkdownContent()).toHaveAttribute('data-content', '`\\\\server\\share\\file.txt`')
  })

  it('does not wrap backslash strings that are not UNC paths', () => {
    const itemWithBackslashes = {
      ...mockItem,
      content: '\\not-a-unc',
    }
    render(<BasicContent item={itemWithBackslashes as ChatItem} />)
    expect(getMarkdownContent()).toHaveAttribute('data-content', '\\not-a-unc')
  })

  it('applies error class when isError is true', () => {
    const errorItem = {
      ...mockItem,
      isError: true,
    }
    render(<BasicContent item={errorItem as ChatItem} />)
    expect(getMarkdownContent()).toHaveClass('text-[#F04438]!')
  })
})

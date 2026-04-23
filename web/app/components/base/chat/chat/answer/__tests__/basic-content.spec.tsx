import type { ReactNode } from 'react'
import type { ChatItem } from '../../../types'
import type { MarkdownProps } from '@/app/components/base/markdown'
import { render, screen } from '@testing-library/react'
import BasicContent from '../basic-content'

vi.mock('@thesysai/genui-sdk', () => ({
  ThemeProvider: ({ children }: { children: ReactNode }) => children,
  C1Component: ({ c1Response }: { c1Response: string }) => (
    <div data-testid="c1-component" data-response={c1Response}>
      {c1Response}
    </div>
  ),
}))

// Mock Markdown component used only in tests
vi.mock('@/app/components/base/markdown', () => ({
  Markdown: ({ content, className }: MarkdownProps) => (
    <div data-testid="basic-content-markdown" data-content={String(content)} className={className}>
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

  it('renders content correctly', () => {
    render(<BasicContent item={mockItem as ChatItem} />)
    const markdown = screen.getByTestId('basic-content-markdown')
    expect(markdown).toHaveAttribute('data-content', 'Hello World')
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
    const markdown = screen.getByTestId('basic-content-markdown')
    expect(markdown).toHaveAttribute('data-content', 'Annotated Content')
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
    expect(screen.getByTestId('basic-content-markdown')).toHaveAttribute('data-content', '')

    const itemWithUndefinedAnnotation = {
      ...mockItem,
      annotation: {
        logAnnotation: {},
      },
    }
    rerender(<BasicContent item={itemWithUndefinedAnnotation as ChatItem} />)
    expect(screen.getByTestId('basic-content-markdown')).toHaveAttribute('data-content', '')
  })

  it('wraps Windows UNC paths in backticks', () => {
    const itemWithUNC = {
      ...mockItem,
      content: '\\\\server\\share\\file.txt',
    }
    render(<BasicContent item={itemWithUNC as ChatItem} />)
    const markdown = screen.getByTestId('basic-content-markdown')
    expect(markdown).toHaveAttribute('data-content', '`\\\\server\\share\\file.txt`')
  })

  it('does not wrap content in backticks if it already is', () => {
    const itemWithBackticks = {
      ...mockItem,
      content: '`\\\\server\\share\\file.txt`',
    }
    render(<BasicContent item={itemWithBackticks as ChatItem} />)
    const markdown = screen.getByTestId('basic-content-markdown')
    expect(markdown).toHaveAttribute('data-content', '`\\\\server\\share\\file.txt`')
  })

  it('does not wrap backslash strings that are not UNC paths', () => {
    const itemWithBackslashes = {
      ...mockItem,
      content: '\\not-a-unc',
    }
    render(<BasicContent item={itemWithBackslashes as ChatItem} />)
    const markdown = screen.getByTestId('basic-content-markdown')
    expect(markdown).toHaveAttribute('data-content', '\\not-a-unc')
  })

  it('applies error class when isError is true', () => {
    const errorItem = {
      ...mockItem,
      isError: true,
    }
    render(<BasicContent item={errorItem as ChatItem} />)
    const markdown = screen.getByTestId('basic-content-markdown')
    expect(markdown).toHaveClass('text-[#F04438]!')
  })
})

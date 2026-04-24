import type { ReactNode } from 'react'
import type { ChatItem } from '../../../types'
import type { IThoughtProps } from '@/app/components/base/chat/chat/thought'
import type { FileEntity } from '@/app/components/base/file-uploader/types'
import type { MarkdownProps } from '@/app/components/base/markdown'
import { render, screen, within } from '@testing-library/react'
import AgentContent from '../agent-content'

vi.mock('@thesysai/genui-sdk', () => ({
  ThemeProvider: ({ children }: { children: ReactNode }) => children,
  C1Component: ({ c1Response }: { c1Response: string }) => (
    <div data-testid="c1-component" data-response={c1Response}>
      {c1Response}
    </div>
  ),
}))

// Mock Markdown component used only in tests. The real `Markdown` always
// renders `<div data-testid="markdown-body">`, and doesn't forward caller
// `data-testid`; the wrapping div on the agent-content path carries the test
// id instead.
vi.mock('@/app/components/base/markdown', () => ({
  Markdown: (props: MarkdownProps & { 'data-testid'?: string }) => (
    <div data-testid={props['data-testid'] || 'markdown-mock'} data-content={String(props.content)} className={props.className}>
      {String(props.content)}
    </div>
  ),
}))

// Mock Thought
vi.mock('@/app/components/base/chat/chat/thought', () => ({
  default: ({ thought, isFinished }: IThoughtProps) => (
    <div data-testid="thought-component" data-finished={isFinished}>
      {thought.thought}
    </div>
  ),
}))

// Mock FileList and Utils
vi.mock('@/app/components/base/file-uploader', () => ({
  FileList: ({ files }: { files: FileEntity[] }) => (
    <div data-testid="file-list-component">
      {files.map(f => f.name).join(', ')}
    </div>
  ),
}))

vi.mock('@/app/components/base/file-uploader/utils', () => ({
  getProcessedFilesFromResponse: (files: FileEntity[]) => files.map(f => ({ ...f, name: `processed-${f.id}` })),
}))

describe('AgentContent', () => {
  const mockItem: ChatItem = {
    id: '1',
    content: '',
    isAnswer: true,
  }

  const getAnnotationMarkdown = () =>
    within(screen.getByTestId('agent-content-markdown')).getByTestId('markdown-mock')

  it('renders logAnnotation if present', () => {
    const itemWithAnnotation = {
      ...mockItem,
      annotation: {
        logAnnotation: { content: 'Log Annotation Content' },
      },
    }
    render(<AgentContent item={itemWithAnnotation as ChatItem} />)
    expect(getAnnotationMarkdown()).toHaveAttribute('data-content', 'Log Annotation Content')
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
    render(<AgentContent item={itemWithC1LookingAnnotation as ChatItem} />)

    expect(screen.queryByTestId('agent-content-c1')).not.toBeInTheDocument()
    expect(screen.queryByTestId('c1-component')).not.toBeInTheDocument()
    expect(getAnnotationMarkdown()).toHaveAttribute('data-content', '<content><Card title="From annotation" /></content>')
  })

  it('renders empty string if logAnnotation content is missing', () => {
    const itemWithEmptyAnnotation = {
      ...mockItem,
      annotation: {
        logAnnotation: { content: '' },
      },
    }
    const { rerender } = render(<AgentContent item={itemWithEmptyAnnotation as ChatItem} />)
    expect(getAnnotationMarkdown()).toHaveAttribute('data-content', '')

    const itemWithUndefinedAnnotation = {
      ...mockItem,
      annotation: {
        logAnnotation: {},
      },
    }
    rerender(<AgentContent item={itemWithUndefinedAnnotation as ChatItem} />)
    expect(getAnnotationMarkdown()).toHaveAttribute('data-content', '')
  })

  it('renders content prop if provided and no annotation', () => {
    render(<AgentContent item={mockItem} content="Direct Content" />)
    const markdown = within(screen.getByTestId('agent-content-markdown')).getByTestId('markdown-mock')
    expect(markdown).toHaveAttribute('data-content', 'Direct Content')
  })

  it('renders C1 content with the C1 renderer', () => {
    render(
      <AgentContent
        item={mockItem}
        content="<content><Card title='Agent response' /></content>"
      />,
    )

    expect(screen.getByTestId('agent-content-c1')).toBeInTheDocument()
    expect(screen.getByTestId('c1-component')).toHaveAttribute('data-response', '<content><Card title=\'Agent response\' /></content>')
  })

  it('renders agent_thoughts if content is absent', () => {
    const itemWithThoughts = {
      ...mockItem,
      agent_thoughts: [
        { thought: 'Thought 1', tool: 'tool1' },
        { thought: 'Thought 2' },
      ],
    }
    render(<AgentContent item={itemWithThoughts as ChatItem} responding={false} />)
    const items = screen.getAllByTestId('agent-thought-item')
    expect(items).toHaveLength(2)
    const thoughtMarkdowns = screen.getAllByTestId('agent-thought-markdown')
    expect(thoughtMarkdowns[0]).toHaveTextContent('Thought 1')
    expect(thoughtMarkdowns[1]).toHaveTextContent('Thought 2')
    expect(screen.getByTestId('thought-component')).toHaveTextContent('Thought 1')
  })

  it('passes correct isFinished to Thought component', () => {
    const itemWithThoughts = {
      ...mockItem,
      agent_thoughts: [
        { thought: 'T1', tool: 'tool1', observation: 'obs1' }, // finished by observation
        { thought: 'T2', tool: 'tool2' }, // finished by responding=false
      ],
    }
    const { rerender } = render(<AgentContent item={itemWithThoughts as ChatItem} responding={true} />)
    const thoughts = screen.getAllByTestId('thought-component')
    expect(thoughts[0]).toHaveAttribute('data-finished', 'true')
    expect(thoughts[1]).toHaveAttribute('data-finished', 'false')

    rerender(<AgentContent item={itemWithThoughts as ChatItem} responding={false} />)
    expect(screen.getAllByTestId('thought-component')[1]).toHaveAttribute('data-finished', 'true')
  })

  it('renders FileList if thought has message_files', () => {
    const itemWithFiles = {
      ...mockItem,
      agent_thoughts: [
        {
          thought: 'T1',
          message_files: [{ id: 'file1' }, { id: 'file2' }],
        },
      ],
    }
    render(<AgentContent item={itemWithFiles as ChatItem} />)
    expect(screen.getByTestId('file-list-component')).toHaveTextContent('processed-file1, processed-file2')
  })

  it('renders nothing if no annotation, content, or thoughts', () => {
    render(<AgentContent item={mockItem} />)
    expect(screen.getByTestId('agent-content-container')).toBeEmptyDOMElement()
  })
})

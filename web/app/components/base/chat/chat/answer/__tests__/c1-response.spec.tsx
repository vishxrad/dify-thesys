import type { ReactNode } from 'react'
import { render, screen } from '@testing-library/react'
import C1Response from '../c1-response'

type MockAction = {
  type?: string
  params?: {
    url?: string
    humanFriendlyMessage?: string
    llmFriendlyMessage?: string
  }
  humanFriendlyMessage?: string
  llmFriendlyMessage?: string
}

type MockC1ComponentProps = {
  c1Response: string
  isStreaming: boolean
  onAction?: (event: MockAction) => void
}

const mockOnSend = vi.fn()
let mockReadonly = false
let latestC1Props: MockC1ComponentProps | null = null

vi.mock('../../context', () => ({
  useChatContext: () => ({
    onSend: mockOnSend,
    readonly: mockReadonly,
  }),
}))

vi.mock('@thesysai/genui-sdk', () => ({
  ThemeProvider: ({ children }: { children: ReactNode }) => (
    <div data-testid="c1-theme-provider">{children}</div>
  ),
  C1Component: (props: MockC1ComponentProps) => {
    latestC1Props = props
    return (
      <div
        data-testid="c1-component"
        data-response={props.c1Response}
        data-streaming={String(props.isStreaming)}
      >
        {props.c1Response}
      </div>
    )
  },
}))

describe('C1Response', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockReadonly = false
    latestC1Props = null
  })

  // Covers the basic render contract from the wrapper into the SDK component.
  describe('Rendering', () => {
    it('should render the C1 component with the response and streaming state', () => {
      render(
        <C1Response
          content="<content><Card title='Hello' /></content>"
          dataTestId="answer-c1"
          responding={true}
        />,
      )

      expect(screen.getByTestId('answer-c1')).toBeInTheDocument()
      expect(screen.getByTestId('c1-theme-provider')).toBeInTheDocument()
      expect(screen.getByTestId('c1-component')).toHaveAttribute('data-response', '<content><Card title=\'Hello\' /></content>')
      expect(screen.getByTestId('c1-component')).toHaveAttribute('data-streaming', 'true')
    })
  })

  // Covers the action plumbing needed for interactive C1 content inside Dify chat.
  describe('Actions', () => {
    it('should send the llmFriendlyMessage for continue conversation actions', () => {
      render(
        <C1Response
          content="<content />"
          dataTestId="answer-c1"
        />,
      )

      latestC1Props?.onAction?.({
        type: 'continue_conversation',
        params: {
          humanFriendlyMessage: 'Show flights',
          llmFriendlyMessage: 'User selected the morning flights filter.',
        },
      })

      expect(mockOnSend).toHaveBeenCalledWith('User selected the morning flights filter.')
    })

    it('should open a new tab for open_url actions', () => {
      const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)

      render(
        <C1Response
          content="<content />"
          dataTestId="answer-c1"
        />,
      )

      latestC1Props?.onAction?.({
        type: 'open_url',
        params: {
          url: 'https://example.com',
        },
      })

      expect(openSpy).toHaveBeenCalledWith('https://example.com', '_blank', 'noopener,noreferrer')

      openSpy.mockRestore()
    })

    it('should ignore conversation actions when the chat is readonly', () => {
      mockReadonly = true

      render(
        <C1Response
          content="<content />"
          dataTestId="answer-c1"
        />,
      )

      latestC1Props?.onAction?.({
        type: 'continue_conversation',
        params: {
          llmFriendlyMessage: 'This should not be sent.',
        },
      })

      expect(mockOnSend).not.toHaveBeenCalled()
    })
  })
})

import { detectResponseFormat } from '../detect-response-format'

describe('detectResponseFormat', () => {
  // Covers plain-text and markdown answers that should keep using the Markdown renderer.
  describe('Markdown responses', () => {
    it('should return markdown when the content is plain markdown', () => {
      expect(detectResponseFormat('## Hello\n\nThis is markdown.')).toBe('markdown')
    })

    it('should return markdown when C1 tags appear later in markdown content', () => {
      expect(detectResponseFormat('Example XML tag: <content>not a C1 payload</content>')).toBe('markdown')
    })
  })

  // Covers the XML-like C1 payload markers documented by Thesys.
  describe('C1 responses (fully received)', () => {
    it('should return c1 when the response has a matching closing tag', () => {
      expect(detectResponseFormat('<content><Card title="Hello" /></content>')).toBe('c1')
    })

    it('should return c1 for custom_markdown with a closing tag', () => {
      expect(detectResponseFormat('<custom_markdown>Fallback content</custom_markdown>')).toBe('c1')
    })
  })

  // A partial C1 payload arriving mid-stream should stay as markdown until it
  // either closes or the stream ends, so the SDK never renders its
  // "could not parse" state on a half-open payload.
  describe('C1 responses (streaming)', () => {
    it('should return markdown while a C1 payload is still incomplete', () => {
      expect(detectResponseFormat('<content thesys="true">{"partial":', { stable: false })).toBe('markdown')
    })

    it('should return c1 once the stream is marked stable even without a close tag', () => {
      expect(detectResponseFormat('<content thesys="true">{"partial":', { stable: true })).toBe('c1')
    })

    it('should return c1 as soon as the close tag arrives, regardless of stability', () => {
      const closed = '<content thesys="true">{"ok":true}</content>'
      expect(detectResponseFormat(closed, { stable: false })).toBe('c1')
      expect(detectResponseFormat(closed, { stable: true })).toBe('c1')
    })
  })
})

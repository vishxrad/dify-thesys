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
  describe('C1 responses', () => {
    it('should return c1 when the response contains a content tag', () => {
      expect(detectResponseFormat('<content><Card title="Hello" /></content>')).toBe('c1')
    })

    it('should return c1 when the response contains custom markdown tags', () => {
      expect(detectResponseFormat('<custom_markdown>Fallback content</custom_markdown>')).toBe('c1')
    })
  })
})

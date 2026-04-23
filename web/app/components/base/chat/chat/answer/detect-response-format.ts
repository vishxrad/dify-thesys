export type ResponseFormat = 'markdown' | 'c1'

const C1_RESPONSE_TAG_PATTERN = /^\s*<(?:thinking|content|artifact|custom_markdown)(?:\s[^>]*)?>/i

export const detectResponseFormat = (content: string): ResponseFormat => {
  if (C1_RESPONSE_TAG_PATTERN.test(content))
    return 'c1'

  return 'markdown'
}

export type ResponseFormat = 'markdown' | 'c1'

const C1_OPEN_TAG_PATTERN = /^\s*<(thinking|content|artifact|custom_markdown)(?:\s[^>]*)?>/i

export type DetectOptions = {
  // True once the stream has finished. We delay the switch to C1 while a
  // partial payload is still arriving so the SDK never renders its "could not
  // parse" state on a half-open tag.
  stable?: boolean
}

export const detectResponseFormat = (content: string, opts?: DetectOptions): ResponseFormat => {
  const match = C1_OPEN_TAG_PATTERN.exec(content)
  if (!match)
    return 'markdown'

  const closingTag = `</${match[1]}>`
  if (content.includes(closingTag))
    return 'c1'

  return opts?.stable ? 'c1' : 'markdown'
}

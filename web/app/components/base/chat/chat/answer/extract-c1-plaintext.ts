/**
 * Extract readable plaintext from a Thesys C1 response.
 *
 * Thesys generative-UI responses come wrapped in an XML envelope:
 *   <content thesys="true" version="1">  {JSON component tree}     </content>
 *   <content thesys="true" version="2">  ```openui-lang\n...\n```  </content>
 *
 * `message.answer` stores the raw wrapper. Downstream consumers that need
 * natural-language prose (copy-to-clipboard, TTS, cross-provider chaining,
 * etc.) materialise plaintext on demand via `extractC1Plaintext(content)`.
 *
 * Keep this in sync with `api/libs/c1_plaintext.py` — both use the same
 * component formatter table so the two representations agree.
 */

const CONTENT_ENVELOPE = /<content\b([^>]*)>([\s\S]*?)<\/content>/i
const VERSION_ATTR = /\bversion\s*=\s*["'](\d+)["']/i
// Explicit [ \t]* instead of \s* so the non-greedy `[\s\S]*?` capture in the
// middle can't back-track across newlines into this prefix/suffix and cause
// super-linear matching (caught by eslint-plugin-regexp).
const OPENUI_FENCE = /```[ \t]*openui-lang[ \t]*\n([\s\S]*?)\n[ \t]*```/i
const STATEMENT = /^\s*(\$?\w+)\s*=\s*(\w+)\s*\(([\s\S]*)\)\s*$/
const STRING_LITERAL = /"((?:[^"\\]|\\.)*)"/g

const HTML_ENTITY_MAP: Record<string, string> = {
  '&quot;': '"',
  '&#34;': '"',
  '&apos;': '\'',
  '&#39;': '\'',
  '&lt;': '<',
  '&#60;': '<',
  '&gt;': '>',
  '&#62;': '>',
  '&amp;': '&',
  '&#38;': '&',
  '&nbsp;': ' ',
}
const HTML_ENTITY = /&(?:quot|apos|lt|gt|amp|nbsp|#34|#39|#60|#62|#38);/g

// Components whose visible output is their children — we skip them and let
// each child render on its own line.
const CONTAINER_COMPONENTS = new Set([
  'Card',
  'Section',
  'SectionBlock',
  'CompositeCardBlock',
  'CompositeCardItem',
  'ContextCardBlock',
  'Container',
  'Stack',
  'Row',
  'Column',
])

// Components that are plumbing, never user-facing prose.
const SKIP_COMPONENTS = new Set(['Query', 'Mutation', 'Icon'])

// JSON (v1) component prop names that typically hold user-facing prose.
const TEXT_JSON_KEYS = new Set([
  'title',
  'subtitle',
  'description',
  'label',
  'text',
  'heading',
  'caption',
  'markdown',
  'content',
  'body',
])

type Formatter = (strings: string[]) => string

const formatDefault: Formatter = strings =>
  strings.filter(s => s).join(' ')

const formatHeader: Formatter = (strings) => {
  if (strings.length === 0)
    return ''
  let out = `# ${strings[0]}`
  if (strings.length >= 2 && strings[1])
    out += `\n_${strings[1]}_`
  return out
}

const formatInlineHeader: Formatter = (strings) => {
  if (strings.length === 0)
    return ''
  let out = `**${strings[0]}**`
  if (strings.length >= 2 && strings[1])
    out += ` — ${strings[1]}`
  return out
}

const formatIconText: Formatter = (strings) => {
  // IconText(icon_ref, variant, size, title, description, …) — icon_ref is
  // a variable reference so it never lands in `strings`.
  if (strings.length === 0)
    return ''
  const title = strings.length > 1 ? strings[1] : strings[0]
  const desc = strings.length > 2 ? strings[2] : ''
  const parts: string[] = []
  if (title)
    parts.push(`**${title}**`)
  if (desc)
    parts.push(`— ${desc}`)
  return parts.join(' ')
}

const formatText: Formatter = strings =>
  strings.length > 1 ? strings[1] : (strings[0] ?? '')

const FORMATTERS: Record<string, Formatter> = {
  Header: formatHeader,
  InlineHeader: formatInlineHeader,
  TextContent: strings => strings[0] ?? '',
  Text: formatText,
  Button: strings => (strings[0] ? `[button: ${strings[0]}]` : ''),
  IconButton: strings => (strings[0] ? `[button: ${strings[0]}]` : ''),
  IconText: formatIconText,
  FollowUpBlock: strings =>
    strings.length ? `Follow-ups: ${strings.filter(s => s).join(' · ')}` : '',
  Image: strings => (strings.length > 1 && strings[1] ? `[image: ${strings[1]}]` : '[image]'),
  BarChart: () => '[bar chart]',
  LineChart: () => '[line chart]',
  PieChart: () => '[pie chart]',
  AreaChart: () => '[area chart]',
  RadarChart: () => '[radar chart]',
  RadialChart: () => '[radial chart]',
  ScatterChart: () => '[scatter chart]',
  Table: () => '[table]',
  Slider: strings => (strings[0] ? `[slider: ${strings[0]}]` : '[slider]'),
  Callout: strings => strings[0] ?? '',
  Alert: strings => strings[0] ?? '',
}

const decodeEntities = (raw: string): string =>
  raw.replace(HTML_ENTITY, match => HTML_ENTITY_MAP[match] ?? match)

export const isC1Content = (content: string | null | undefined): boolean =>
  !!content && CONTENT_ENVELOPE.test(content)

export const extractC1Plaintext = (content: string | null | undefined): string => {
  if (!content)
    return ''
  const match = CONTENT_ENVELOPE.exec(content)
  if (!match)
    return content.trim()

  const [, attrs, inner] = match
  const decoded = decodeEntities(inner).trim()
  const versionMatch = VERSION_ATTR.exec(attrs)
  const version = versionMatch ? Number.parseInt(versionMatch[1], 10) : 1

  return version >= 2
    ? extractFromOpenUILang(decoded)
    : extractFromJson(decoded)
}

function extractFromOpenUILang(body: string): string {
  const fenceMatch = OPENUI_FENCE.exec(body)
  const source = fenceMatch ? fenceMatch[1].trim() : body

  const segments: string[] = []
  for (const rawLine of source.split('\n')) {
    const line = rawLine.trim()
    if (!line)
      continue
    const statementMatch = STATEMENT.exec(line)
    if (!statementMatch)
      continue
    const [, name, component, args] = statementMatch
    if (name.startsWith('$'))
      continue
    if (CONTAINER_COMPONENTS.has(component) || SKIP_COMPONENTS.has(component))
      continue

    const stringArgs: string[] = []
    for (const m of args.matchAll(STRING_LITERAL))
      stringArgs.push(m[1])

    const formatter = FORMATTERS[component] ?? formatDefault
    const rendered = formatter(stringArgs).trim()
    if (rendered)
      segments.push(rendered)
  }

  return segments.join('\n\n').trim()
}

function collectJsonText(node: unknown, out: string[]): void {
  if (node === null || node === undefined)
    return
  if (typeof node === 'string')
    return
  if (Array.isArray(node)) {
    for (const item of node)
      collectJsonText(item, out)
    return
  }
  if (typeof node === 'object') {
    for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
      if (TEXT_JSON_KEYS.has(key) && typeof value === 'string')
        out.push(value)
      else if (typeof value === 'object' && value !== null)
        collectJsonText(value, out)
    }
  }
}

function extractFromJson(body: string): string {
  try {
    const tree = JSON.parse(body)
    const pieces: string[] = []
    collectJsonText(tree, pieces)
    return pieces.filter(p => p).join(' ').trim()
  }
  catch {
    // Fall back to a coarse string-literal sweep so partial / malformed v1
    // payloads still surface *something* rather than silently returning empty.
    const strings: string[] = []
    for (const m of body.matchAll(STRING_LITERAL))
      strings.push(m[1])
    return strings.filter(s => s).join(' ').trim()
  }
}

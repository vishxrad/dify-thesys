import { extractC1Plaintext, isC1Content } from '../extract-c1-plaintext'

describe('isC1Content', () => {
  it('returns false for empty / null / undefined', () => {
    expect(isC1Content('')).toBe(false)
    expect(isC1Content(null)).toBe(false)
    expect(isC1Content(undefined)).toBe(false)
  })

  it('returns false for plain markdown', () => {
    expect(isC1Content('Hello, world.')).toBe(false)
    expect(isC1Content('## Heading\n\nbody')).toBe(false)
  })

  it('returns true when the Thesys content envelope is present', () => {
    expect(isC1Content('<content thesys="true">{"component":"Card"}</content>')).toBe(true)
    expect(isC1Content('<content thesys="true" version="2">body</content>')).toBe(true)
  })
})

describe('extractC1Plaintext — pass through', () => {
  it('returns non-C1 content unchanged', () => {
    expect(extractC1Plaintext('Hello, world.')).toBe('Hello, world.')
  })

  it('returns empty string for empty / null / undefined', () => {
    expect(extractC1Plaintext('')).toBe('')
    expect(extractC1Plaintext(null)).toBe('')
    expect(extractC1Plaintext(undefined)).toBe('')
  })
})

describe('extractC1Plaintext — openui-lang (v2)', () => {
  it('extracts header and body text', () => {
    const content = '<content thesys="true" version="2">\n```openui-lang\n'
      + 'root = Card([header, body])\n'
      + 'header = Header("Hello!", "How can I help you today?")\n'
      + 'body = TextContent("I can plan trips and build dashboards.")\n'
      + '```\n</content>'

    const result = extractC1Plaintext(content)
    expect(result).toContain('Hello!')
    expect(result).toContain('How can I help you today?')
    expect(result).toContain('I can plan trips and build dashboards.')
    // Card is a container → not emitted literally
    expect(result).not.toContain('Card(')
  })

  it('decodes HTML entities in string literals', () => {
    const content = '<content thesys="true" version="2">\n```openui-lang\n'
      + 'greeting = TextContent(&quot;Hello, I&#39;m here.&quot;)\n'
      + '```\n</content>'

    expect(extractC1Plaintext(content)).toBe('Hello, I\'m here.')
  })

  it('joins FollowUpBlock options into a single line', () => {
    const content = '<content thesys="true" version="2">\n```openui-lang\n'
      + 'fu = FollowUpBlock(["Plan a trip", "Build a form", "Summarise a doc"])\n'
      + '```\n</content>'

    expect(extractC1Plaintext(content)).toBe(
      'Follow-ups: Plan a trip · Build a form · Summarise a doc',
    )
  })

  it('skips state declarations', () => {
    const content = '<content thesys="true" version="2">\n```openui-lang\n'
      + '$days = "7"\n'
      + 'header = Header("Pick a range", "")\n'
      + '```\n</content>'

    const result = extractC1Plaintext(content)
    expect(result).not.toContain('7')
    expect(result).toContain('Pick a range')
  })

  it('skips Icon and Query plumbing', () => {
    const content = '<content thesys="true" version="2">\n```openui-lang\n'
      + 'ic = Icon("map", "travel")\n'
      + 'data = Query("fetchOrders", {}, {rows: []})\n'
      + 'msg = TextContent("visible text")\n'
      + '```\n</content>'

    expect(extractC1Plaintext(content)).toBe('visible text')
  })

  it('falls back to string extraction for unknown components', () => {
    const content = '<content thesys="true" version="2">\n```openui-lang\n'
      + 'weird = FancyNewWidget("meaningful label", "more prose")\n'
      + '```\n</content>'

    expect(extractC1Plaintext(content)).toBe('meaningful label more prose')
  })

  it('emits a semantic placeholder for charts', () => {
    const content = '<content thesys="true" version="2">\n```openui-lang\n'
      + 'chart = BarChart(data)\n'
      + '```\n</content>'

    expect(extractC1Plaintext(content)).toBe('[bar chart]')
  })

  it('degrades gracefully on malformed bodies', () => {
    const content = '<content thesys="true" version="2">\nnot a statement at all\n</content>'
    expect(extractC1Plaintext(content)).toBe('')
  })
})

describe('extractC1Plaintext — JSON (v1)', () => {
  it('walks the component tree collecting text props', () => {
    const content = '<content thesys="true">'
      + '{"component":"Card","props":{"children":['
      + '{"component":"Header","props":{"title":"Hello","description":"Welcome back."}},'
      + '{"component":"TextContent","props":{"content":"Body prose goes here."}}'
      + ']}}'
      + '</content>'

    const result = extractC1Plaintext(content)
    expect(result).toContain('Hello')
    expect(result).toContain('Welcome back.')
    expect(result).toContain('Body prose goes here.')
  })

  it('falls back to a string-literal sweep on malformed JSON', () => {
    const content = '<content thesys="true">'
      + '{"component":"Card","props":{"children":[{"component":"Header","props"'
      + '</content>'

    const result = extractC1Plaintext(content)
    expect(result !== '').toBe(true)
  })
})

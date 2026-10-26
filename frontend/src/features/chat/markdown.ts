/**
 * Minimal, safe Markdown for assistant replies.
 *
 * The whole text is HTML-escaped first; only a fixed set of tags is produced
 * afterwards (p, br, strong, em, code, ul/ol/li, a). Links accept http(s) only and
 * open in a new tab with rel="noopener noreferrer", so model output can never
 * inject markup or script.
 */
const ESCAPES: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

export function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ESCAPES[char])
}

const LINK_ATTRS = 'target="_blank" rel="noopener noreferrer"'

function inline(text: string): string {
  return text
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>')
    .replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, `<a href="$2" ${LINK_ATTRS}>$1</a>`)
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, `$1<a href="$2" ${LINK_ATTRS}>$2</a>`)
}

export function renderMarkdown(source: string): string {
  const lines = escapeHtml((source || '').replace(/\r\n?/g, '\n')).split('\n')
  const html: string[] = []
  let list: 'ul' | 'ol' | null = null
  let paragraph: string[] = []
  const flush = () => {
    if (paragraph.length) html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`)
    paragraph = []
  }
  const closeList = () => {
    if (list) html.push(`</${list}>`)
    list = null
  }
  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      flush()
      closeList()
      continue
    }
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line)
    const numbered = /^\s*(\d+)[.)]\s+(.*)$/.exec(line)
    if (bullet || numbered) {
      flush()
      const kind = bullet ? 'ul' : 'ol'
      if (list !== kind) {
        closeList()
        const start = numbered && numbered[1] !== '1' ? ` start="${Number(numbered[1])}"` : ''
        html.push(`<${kind}${kind === 'ol' ? start : ''}>`)
        list = kind
      }
      html.push(`<li>${inline(bullet ? bullet[1] : numbered![2])}</li>`)
      continue
    }
    closeList()
    const heading = /^\s*#{1,6}\s+(.*)$/.exec(line)
    if (heading) {
      flush()
      html.push(`<p><strong>${inline(heading[1])}</strong></p>`)
      continue
    }
    paragraph.push(line)
  }
  flush()
  closeList()
  return html.join('')
}

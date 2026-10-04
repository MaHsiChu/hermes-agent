import { localizedReason } from '../lib/reasons'
import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Message } from '../lib/protocol'
import { dateLabel } from '../lib/models'
import { sessionPath } from '../lib/api'

function Markdown({ text }: { text: string }) {
  const html = useMemo(
    () =>
      DOMPurify.sanitize(marked.parse(text, { async: false }), {
        USE_PROFILES: { html: true },
        FORBID_TAGS: ['img', 'style', 'input', 'form', 'button', 'video', 'audio'],
        FORBID_ATTR: ['style']
      }),
    [text]
  )
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
}
function LongOutput({ label, children, long = true }: { label: string; children: React.ReactNode; long?: boolean }) {
  return long ? (
    <details className="output">
      <summary>{label} · 展开完整内容</summary>
      {children}
    </details>
  ) : (
    <>{children}</>
  )
}
function Block({ block, session }: { block: unknown; session: string }) {
  if (typeof block === 'string')
    return (
      <LongOutput label="长文本" long={block.length > 3000}>
        <Markdown text={block} />
      </LongOutput>
    )
  if (!block || typeof block !== 'object') return <pre>{JSON.stringify(block)}</pre>
  const value = block as Record<string, unknown>
  if (value.type === 'attachment' || value.type === 'image' || value.type === 'image_url') {
    if (value.status === 'available' && typeof value.id === 'string') {
      const src = `${sessionPath(session)}/attachments/${encodeURIComponent(value.id)}`
      return (
        <figure>
          <a href={src} target="_blank" rel="noreferrer">
            <img loading="lazy" src={src} alt={String(value.name || '会话图片')} />
          </a>
          <figcaption>{String(value.name || '图片')}</figcaption>
        </figure>
      )
    }
    return <p className="muted">图片不可用：{localizedReason(String(value.reason || '来源未授权导出此图片'))}</p>
  }
  if (['text', 'markdown', 'output_text', 'input_text'].includes(String(value.type)) && typeof value.text === 'string')
    return <Block block={value.text} session={session} />
  const content =
    typeof value.text === 'string'
      ? value.text
      : typeof value.content === 'string'
        ? value.content
        : JSON.stringify(value, null, 2)
  const title =
    (
      {
        tool_call: '工具调用',
        tool_result: '工具结果',
        tool_use: '工具输入',
        diff: '文件变更',
        code: '代码',
        thinking: '思考过程'
      } as Record<string, string>
    )[String(value.type)] || String(value.name || value.type || '结构化内容')
  return (
    <LongOutput label={title} long={content.length > 1200 || String(value.type).includes('tool')}>
      <div className="block-label">{title}</div>
      <pre className={value.type === 'diff' ? 'diff' : ''}>{content}</pre>
    </LongOutput>
  )
}
export function Transcript({ messages, session }: { messages: Message[]; session: string }) {
  const visible = messages.filter(message => !message.deleted)
  return (
    <div className="transcript">
      {visible.map(message => (
        <article className={`message role-${message.role || 'system'}`} key={message.id} data-message-id={message.id}>
          <header>
            <strong>
              {({ user: '你', assistant: '助手', tool: '工具', system: '系统' } as Record<string, string>)[
                message.role || 'system'
              ] || message.role}
            </strong>
            <time>{message.timestamp ? dateLabel(message.timestamp) : ''}</time>
          </header>
          {typeof message.content === 'string' ? (
            <Block block={message.content} session={session} />
          ) : (
            message.content?.map((block, index) => <Block key={`content-${index}`} block={block} session={session} />)
          )}
          {message.blocks?.map((block, index) => (
            <Block key={`block-${index}`} block={block} session={session} />
          ))}
          {message.tool_calls?.map((block, index) => (
            <LongOutput key={`tool-${index}`} label="工具调用">
              <pre>{JSON.stringify(block, null, 2)}</pre>
            </LongOutput>
          ))}
          {message.tool_call_id && <small className="muted">调用 ID：{message.tool_call_id}</small>}
        </article>
      ))}
      {!visible.length && <div className="empty">这里还没有可显示的消息。同步后的原始会话会出现在此处。</div>}
    </div>
  )
}

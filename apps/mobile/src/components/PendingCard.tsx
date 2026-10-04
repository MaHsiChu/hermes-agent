import { localizedReason } from '../lib/reasons'
import { useState } from 'react'
import type { Capability, Pending, Question } from '../lib/protocol'
import { canAnswer } from '../lib/models'

function choices(values: unknown[] | undefined) {
  return (values || []).flatMap(value =>
    typeof value === 'string'
      ? [{ value, label: value }]
      : value && typeof value === 'object' && 'label' in value
        ? [{ value: String(('value' in value && value.value) || value.label), label: String(value.label) }]
        : []
  )
}
function selectedValues(value: string): string[] {
  try {
    const parsed: unknown = JSON.parse(value)
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}
function QuestionInput({
  question,
  value,
  locked,
  change
}: {
  question: Question
  value: string
  locked: boolean
  change: (value: string) => void
}) {
  const offered = choices(question.choices)
  const selected = question.multi_select ? selectedValues(value) : []
  return (
    <fieldset disabled={locked}>
      <legend>
        {question.question}
        {locked ? '（已回答）' : ''}
      </legend>
      {offered.length ? (
        offered.map(choice => (
          <label className="choice" key={choice.value}>
            <input
              type={question.multi_select ? 'checkbox' : 'radio'}
              name={question.qid}
              value={choice.value}
              checked={question.multi_select ? selected.includes(choice.value) : value === choice.value}
              onChange={event =>
                change(
                  question.multi_select
                    ? JSON.stringify(
                        event.target.checked
                          ? [...selected, choice.value]
                          : selected.filter(item => item !== choice.value)
                      )
                    : choice.value
                )
              }
            />
            {choice.label}
          </label>
        ))
      ) : (
        <textarea
          aria-label={question.question}
          value={value}
          onChange={event => change(event.target.value)}
          maxLength={16000}
        />
      )}
      {!!offered.length && (
        <label className="muted">
          或填写自定义回答
          <textarea
            aria-label={`${question.question} 自定义回答`}
            value={
              question.multi_select
                ? selected.length
                  ? ''
                  : value === '[]'
                    ? ''
                    : value
                : offered.some(choice => choice.value === value)
                  ? ''
                  : value
            }
            onChange={event => change(event.target.value)}
            maxLength={16000}
            rows={2}
          />
        </label>
      )}
    </fieldset>
  )
}
export function PendingCard({
  pending,
  capability,
  online,
  busy,
  submit,
  now = Date.now() / 1000
}: {
  pending: Pending
  capability?: Capability
  online: boolean
  busy: boolean
  submit: (payload: Record<string, unknown>) => Promise<void>
  now?: number
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({ ...pending.params.answers })
  const currentAnswers = { ...answers, ...pending.params.answers }
  const [error, setError] = useState('')
  const allowed = canAnswer(pending, capability, now)
  const disabled = !allowed || !online || busy
  const stale =
    pending.params.expired || (typeof pending.params.expires_at === 'number' && pending.params.expires_at <= now)
  const send = async (payload: Record<string, unknown>) => {
    try {
      setError('')
      await submit({ pending_request_id: pending.id, ...payload })
    } catch (error) {
      setError(String(error))
    }
  }
  const questions: Question[] = pending.params.questions || [
    {
      qid: '_single',
      question: pending.params.question || '请在电脑端查看完整问题',
      choices: pending.params.choices,
      multi_select: pending.params.multi_select
    }
  ]
  return (
    <section className="pending-card">
      <div className="eyebrow">{pending.method === 'approval' ? '需要你的审批' : '需要你的回答'}</div>
      {pending.params.description && <p>{pending.params.description}</p>}
      {pending.params.command && <pre>{pending.params.command}</pre>}
      {stale && (
        <p role="status" className="danger-text">
          请求已过期，请等待电脑上的新请求。
        </p>
      )}
      {!allowed && !stale && (
        <p className="muted">
          请在电脑端处理。{localizedReason(capability?.reason) || '此请求不支持远程回答，敏感输入仅限本地。'}
        </p>
      )}
      {busy && allowed && online && (
        <p role="status" className="muted">
          请先核对上一条操作的回执，再回答此请求。未确认的操作不会自动重发。
        </p>
      )}
      {pending.method === 'approval' ? (
        <div className="button-row">
          {choices(pending.params.choices)
            .filter(choice => ['once', 'session', 'always', 'deny'].includes(choice.value))
            .map(choice => (
              <button key={choice.value} disabled={disabled} onClick={() => void send({ choice: choice.value })}>
                {
                  (
                    { once: '允许一次', session: '此会话允许', always: '始终允许', deny: '拒绝' } as Record<
                      string,
                      string
                    >
                  )[choice.value]
                }
              </button>
            ))}
        </div>
      ) : (
        pending.method === 'clarify' && (
          <form
            onSubmit={event => {
              event.preventDefault()
              void send(
                pending.params.questions
                  ? {
                      answers: Object.fromEntries(
                        questions.map(question => [question.qid, currentAnswers[question.qid]])
                      )
                    }
                  : { answer: currentAnswers._single }
              )
            }}
          >
            <fieldset disabled={disabled}>
              {questions.map(question => (
                <QuestionInput
                  key={question.qid}
                  question={question}
                  value={currentAnswers[question.qid] || ''}
                  locked={Object.hasOwn(pending.params.answers || {}, question.qid)}
                  change={value => setAnswers({ ...answers, [question.qid]: value })}
                />
              ))}
              <button
                type="submit"
                disabled={
                  questions.every(question => Object.hasOwn(pending.params.answers || {}, question.qid)) ||
                  questions.some(
                    question =>
                      !Object.hasOwn(pending.params.answers || {}, question.qid) &&
                      (!currentAnswers[question.qid]?.trim() ||
                        (question.multi_select && currentAnswers[question.qid] === '[]'))
                  )
                }
              >
                提交回答
              </button>
            </fieldset>
          </form>
        )
      )}
      {error && (
        <p role="alert" className="danger-text">
          {error}
        </p>
      )}
      <small className="muted">以电脑上的待处理请求为准；先提交的有效回答生效。</small>
    </section>
  )
}

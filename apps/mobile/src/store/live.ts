import { atom } from 'nanostores'
export interface NativeEvent {
  type?: unknown
  payload?: unknown
}
export interface LiveState {
  text: string
  reasoning: string
  status: string
  limited: boolean
}
const empty = (): LiveState => ({ text: '', reasoning: '', status: '', limited: false })
export class LiveOutput {
  state = atom<LiveState>(empty())
  clear() {
    this.state.set(empty())
  }
  recovering() {
    this.state.set({ ...empty(), status: '正在恢复实时输出 · 此前未保存的内容将在完成后同步' })
  }
  event(event: NativeEvent) {
    const payload = event.payload && typeof event.payload === 'object' ? (event.payload as Record<string, unknown>) : {}
    const text = typeof payload.text === 'string' ? payload.text : ''
    const current = this.state.get()
    const handlers: Record<string, () => LiveState> = {
      'message.start': () => ({ ...empty(), status: '正在生成' }),
      'message.delta': () => ({ ...current, text: current.text + text, status: '正在生成' }),
      // These events end the temporary segment. Only durable history owns finished output.
      'message.interim': empty,
      'message.complete': empty,
      'reasoning.delta': () => ({ ...current, reasoning: current.reasoning + text }),
      'thinking.delta': () => ({ ...current, reasoning: current.reasoning + text }),
      'reasoning.available': () => ({ ...current, reasoning: text }),
      'status.update': () => ({ ...current, status: text })
    }
    const next = handlers[String(event.type)]?.()
    if (!next) return
    let budget = 262144
    const bounded = (value: string) => {
      const result = value.slice(0, budget)
      if (result.length < value.length) next.limited = true
      budget -= result.length
      return result
    }
    next.text = bounded(next.text)
    next.reasoning = bounded(next.reasoning)
    next.status = next.status.slice(0, 2000)
    this.state.set(next)
  }
}

import { createElement, Fragment, type ReactNode } from 'react'

import { ContribBoundary } from '@/contrib/react/boundary'
import { useContributions } from '@/contrib/react/use-contributions'

export const TASK_REFERENCE_AREA = 'chat.task-reference'

/** A plugin owns one fragment namespace; ordinary and native session links stay with core. */
export interface TaskReferenceContribution {
  namespace: string
  render: (props: { value: string; children?: ReactNode }) => ReactNode
}

/** The user's plain-text transcript uses the same task links as assistant markdown. */
export function TaskReferenceText({ text }: { text: string }) {
  const parts: ReactNode[] = []
  const pattern = /(```[\s\S]*?(?:```|$)|`[^`\n]*`)|\[((?:\\.|[^\]\\\n])+)\]\((#task\/[a-z0-9-]+\/[^\s)]+)\)/g
  let offset = 0

  for (const match of text.matchAll(pattern)) {
    parts.push(text.slice(offset, match.index))
    parts.push(
      match[1] || (
        <TaskReference href={match[3]} key={match.index}>
          {match[2].replace(/\\([\\[\]])/g, '$1')}
        </TaskReference>
      )
    )
    offset = match.index + match[0].length
  }

  parts.push(text.slice(offset))

  return <Fragment>{parts}</Fragment>
}

export function TaskReference({ href, children }: { href: string; children?: ReactNode }) {
  const contributions = useContributions(TASK_REFERENCE_AREA)
  const match = /^#task\/([a-z0-9-]+)\/(.+)$/.exec(href)
  const owner = contributions.find(c => (c.data as TaskReferenceContribution)?.namespace === match?.[1])
  let value = ''

  try {
    value = match ? decodeURIComponent(match[2]) : ''
  } catch {
    // A partial streaming link must remain readable until its value arrives.
  }

  if (!owner || !value) {
    return <span>{children}</span>
  }

  return (
    <ContribBoundary id={owner.id} variant="chip">
      {createElement((owner.data as TaskReferenceContribution).render, { value, children })}
    </ContribBoundary>
  )
}

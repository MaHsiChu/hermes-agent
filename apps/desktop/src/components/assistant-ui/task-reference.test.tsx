import { useStore } from '@nanostores/react'
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { atom } from 'nanostores'
import { afterEach, expect, it, vi } from 'vitest'

import { registry } from '@/contrib/registry'

import { DirectiveContent } from './directive-text'
import { MarkdownTextContent } from './markdown-text'
import { TASK_REFERENCE_AREA } from './task-reference'

afterEach(cleanup)

it('renders a contributed task from real chat markdown, updates live and opens only on click', async () => {
  const status = atom('running')
  const open = vi.fn()

  const dispose = registry.register({
    id: 'test-task-ref',
    area: TASK_REFERENCE_AREA,
    data: {
      namespace: 'test-board',
      render: function TestTaskReference({ value }: { value: string }) {
        const state = useStore(status)

        return <button onClick={() => open(value)}>Task {state}</button>
      }
    }
  })

  try {
    render(
      <>
        <MarkdownTextContent isRunning={false} text="See [Feature](#task/test-board/job%3A123)." />
        <DirectiveContent text="Follow up [Feature](#task/test-board/job%3A123)." />
      </>
    )
    expect(await screen.findAllByRole('button', { name: 'Task running' })).toHaveLength(2)
    act(() => status.set('completed'))
    expect(open).not.toHaveBeenCalled()
    fireEvent.click(screen.getAllByRole('button', { name: 'Task completed' })[1])
    expect(open).toHaveBeenCalledWith('job:123')
    act(dispose)
    expect(screen.queryByRole('button')).toBeNull()
    expect(screen.getAllByText('Feature')).toHaveLength(2)
  } finally {
    dispose()
  }
})

it('keeps unknown or malformed references inert and code examples literal', () => {
  render(
    <MarkdownTextContent
      isRunning={false}
      text={'[Missing](#task/missing/job%3A123) and `[Example](#task/test/job%3A123)`'}
    />
  )
  expect(screen.getByText('Missing')).toBeTruthy()
  expect(screen.queryByRole('link')).toBeNull()
  expect(screen.getByText('[Example](#task/test/job%3A123)')).toBeTruthy()
})

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { group } from '@/components/pane-shell/tree/model'
import { $layoutTree, closeTreePane, noteActiveTreeGroup, revealTreePane } from '@/components/pane-shell/tree/store'
import { registry } from '@/contrib/registry'
import { host } from '@/sdk'

import { useWorkspaceSessions, WorkspaceSessionRows } from './workspace-sessions'

vi.mock('@/i18n', async original => ({
  ...(await original<object>()),
  useI18n: () => ({ t: { common: { close: 'Close' } } })
}))

function List({ query = '' }: { query?: string }) {
  return <WorkspaceSessionRows entries={useWorkspaceSessions(query)} />
}

const disposers: (() => void)[] = []
beforeEach(() => {
  $layoutTree.set(group(['workspace'], { active: 'workspace', id: 'main' }))
  noteActiveTreeGroup('main')
})
afterEach(() => {
  cleanup()
  disposers.splice(0).forEach(dispose => dispose())
  $layoutTree.set(null)
  noteActiveTreeGroup(null)
})

describe('workspace sessions share the original pane lifecycle', () => {
  it('opts in, deduplicates reopening and removes the row through the same Close', () => {
    const closed = vi.fn()
    act(() => {
      disposers.push(host.openWorkspace('sidebar-ordinary', { render: () => null, title: 'Ordinary pane' }))
      disposers.push(
        host.openWorkspace('sidebar-task', {
          onClose: closed,
          render: () => null,
          title: 'Original title',
          sidebarSession: { render: () => <>Original title · Running</> }
        })
      )
    })
    render(<List />)
    expect(screen.queryByText('Ordinary pane')).toBeNull()
    expect(screen.getByRole('button', { name: 'Original title · Running' })).toBeTruthy()
    act(() => {
      host.openWorkspace('sidebar-task', {
        onClose: closed,
        render: () => null,
        title: 'Updated title',
        sidebarSession: { render: () => <>Updated title · Completed</> }
      })
    })
    expect(document.querySelectorAll('[data-workspace-session]')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Updated title · Completed' }))
    expect(registry.getArea('panes').some(p => p.id === 'plugin-workspace:sidebar-task')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Close · Updated title' }))
    expect(closed).toHaveBeenCalledTimes(1)
    expect(document.querySelectorAll('[data-workspace-session]')).toHaveLength(0)
  })

  it('filters by label and external identity; tab Close also removes its row', () => {
    act(() =>
      disposers.push(
        host.openWorkspace('sidebar-search', {
          render: () => null,
          title: 'Task Alpha',
          sidebarSession: { render: () => <>Task Alpha</>, searchText: 'Claude native-123' }
        })
      )
    )
    const view = render(<List query="native-123" />)
    expect(screen.getByText('Task Alpha')).toBeTruthy()
    view.rerender(<List query="missing" />)
    expect(screen.queryByText('Task Alpha')).toBeNull()
    view.rerender(<List query="alpha" />)
    act(() => revealTreePane('plugin-workspace:sidebar-search'))
    expect(screen.getByRole('button', { name: 'Task Alpha' }).getAttribute('aria-current')).toBe('page')
    act(() => closeTreePane('plugin-workspace:sidebar-search'))
    expect(screen.queryByText('Task Alpha')).toBeNull()
  })
})

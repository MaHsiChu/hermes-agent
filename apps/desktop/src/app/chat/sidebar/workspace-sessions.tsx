import { useStore } from '@nanostores/react'
import type { ReactNode } from 'react'

import { closeTreePane, revealTreePane } from '@/components/pane-shell/tree/store'
import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { RowButton } from '@/components/ui/row-button'
import { ContribBoundary, ContribRender } from '@/contrib/react/boundary'
import { useContributions } from '@/contrib/react/use-contributions'
import type { Contribution } from '@/contrib/types'
import { useI18n } from '@/i18n'
import { cn } from '@/lib/utils'
import { $focusedTreePaneId } from '@/store/session-focus'

import { SIDEBAR_ROW_INSET, SIDEBAR_ROW_MIN_H } from './row-geometry'

type WorkspaceSession = Contribution & {
  data: { sidebarSession: { render: () => ReactNode; searchText?: string }; uncloseable?: boolean }
}

export function useWorkspaceSessions(query = '') {
  const panes = useContributions('panes')
  const search = query.toLocaleLowerCase()

  return panes.filter((pane): pane is WorkspaceSession => {
    const data = pane.data as Partial<WorkspaceSession['data']> | undefined

    return (
      typeof data?.sidebarSession?.render === 'function' &&
      `${pane.title ?? ''} ${data.sidebarSession.searchText ?? ''}`.toLocaleLowerCase().includes(search)
    )
  })
}

/** These are open panes, never synthetic backend SessionInfo records. */
export function WorkspaceSessionRows({ entries }: { entries: WorkspaceSession[] }) {
  const active = useStore($focusedTreePaneId)
  const { t } = useI18n()

  return entries.map(entry => (
    <ContribBoundary id={entry.id} key={entry.id} variant="chip">
      <div
        className={cn(
          'group flex min-w-0 shrink-0 items-center rounded-sm',
          SIDEBAR_ROW_MIN_H,
          active === entry.id && 'bg-(--ui-control-hover-background)'
        )}
        data-workspace-session={entry.id}
      >
        <RowButton
          aria-current={active === entry.id ? 'page' : undefined}
          className={cn(
            SIDEBAR_ROW_INSET,
            'flex-1 overflow-hidden text-left text-[0.8125rem] text-(--ui-text-secondary)'
          )}
          onClick={() => revealTreePane(entry.id)}
          title={entry.title}
        >
          <ContribRender render={entry.data.sidebarSession.render} />
        </RowButton>
        {!entry.data.uncloseable && (
          <Button
            aria-label={`${t.common.close} · ${entry.title}`}
            className="shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
            onClick={() => closeTreePane(entry.id)}
            size="icon-xs"
            variant="ghost"
          >
            <Codicon name="close" size="0.75rem" />
          </Button>
        )}
      </div>
    </ContribBoundary>
  ))
}

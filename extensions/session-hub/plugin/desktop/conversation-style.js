export const conversationCss=`
.hub-detail.hub-conversation{padding:12px 24px;gap:6px;overflow:hidden;background:var(--ui-surface-background);color:var(--ui-text-primary)}
.hub-conversation-transcript [data-testid=transcript-scroll]{scrollbar-gutter:stable;padding:20px max(16px,calc((100% - 760px)/2)) 36px!important;overscroll-behavior:contain}
.hub-message{position:relative;padding:16px 0;font-size:14px;line-height:1.8;min-width:0}
.hub-message-label{display:flex;gap:8px;align-items:center;font-size:11px;color:var(--ui-text-tertiary);margin-bottom:6px}
.hub-message-body{display:flex;flex-direction:column;gap:12px;min-width:0}
.hub-message-body p{margin:0 0 12px}.hub-message-body p:last-child{margin-bottom:0}
.hub-message-body ul,.hub-message-body ol{padding-left:24px;margin:8px 0 16px}.hub-message-body li{margin:6px 0}
.hub-message-body h1,.hub-message-body h2,.hub-message-body h3{font-weight:600;margin:18px 0 8px;line-height:1.4}
.hub-message-body h1{font-size:22px}.hub-message-body h2{font-size:19px}.hub-message-body h3{font-size:16px}
.hub-message-body pre{overflow:auto;max-width:100%;font-size:12px;line-height:1.6}.hub-message-body code{font-family:ui-monospace,Consolas,monospace;font-size:.9em}
.hub-message-body table{border-collapse:collapse;display:block;max-width:100%;overflow:auto}.hub-message-body th,.hub-message-body td{border:1px solid var(--ui-stroke-tertiary);padding:8px 12px;text-align:left}
.hub-message-body blockquote{border-left:3px solid var(--ui-stroke-tertiary);padding-left:14px;margin:12px 0;color:var(--ui-text-secondary)}
.hub-message[data-role=user]{margin:22px 0 22px 18%;padding:0;background:none;border-radius:0}
.hub-message[data-role=user]>.hub-message-body:not(:empty){padding:14px 18px;border-radius:20px;background:var(--ui-text-primary);color:var(--ui-surface-background);white-space:normal}
.hub-message[data-role=user]>.hub-attachment-strip{justify-content:flex-end;margin-bottom:10px}
.hub-copy-message{border:0;background:transparent;padding:4px 0;font-size:11px;color:var(--ui-text-tertiary);cursor:pointer;opacity:0;transition:opacity .15s}
.hub-message:hover>.hub-copy-message,.hub-message:focus-within>.hub-copy-message{opacity:1}
.hub-execution{margin:14px 0;color:var(--ui-text-secondary);border-bottom:1px solid var(--ui-stroke-tertiary);padding:0 0 12px}
.hub-execution>summary{font-size:12px;color:var(--ui-text-tertiary);cursor:pointer;padding:6px 0}.hub-execution .hub-message{font-size:13px;padding:6px 0}
.hub-composer{width:min(800px,100%);box-shadow:0 3px 18px #00000005;margin:4px 0 8px}.hub-composer textarea{padding:8px 0;line-height:1.6;outline:none}.hub-composer:focus-within{border-color:var(--ui-text-tertiary)}
.hub-composer-footer small{flex:1;font-size:10px}.hub-composer-footer>button:first-child{font-size:22px;padding:0 8px;border:0;background:none}
.hub-attachment-strip{display:flex;gap:10px;flex-wrap:wrap}.hub-attachment{position:relative;margin-bottom:8px}
.hub-image-button{display:block;border:1px solid var(--ui-stroke-tertiary);border-radius:14px;padding:0;background:transparent;overflow:hidden;cursor:zoom-in}
.hub-image-button img{display:block;width:128px;height:96px;object-fit:contain;background:var(--ui-surface-background)}
.hub-remove-image{position:absolute;right:-5px;top:-5px;border:1px solid var(--ui-stroke-tertiary);background:var(--ui-surface-background);color:var(--ui-text-primary);border-radius:50%;width:22px;height:22px;padding:0;cursor:pointer}
.hub-image-dialog{border:1px solid var(--ui-stroke-tertiary);border-radius:16px;padding:16px;background:var(--ui-surface-background);color:var(--ui-text-primary);max-width:94vw;max-height:94vh;margin:auto;box-shadow:0 12px 80px #0004}
.hub-image-dialog::backdrop{background:#0008}.hub-image-dialog header{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:12px;font-size:12px}.hub-image-dialog header button{border:0;background:none;color:inherit;font-size:24px;cursor:pointer}
.hub-image-dialog>img{display:block;max-width:88vw;max-height:78vh;object-fit:contain}.hub-dragging{outline:2px dashed var(--ui-accent);outline-offset:4px}
.hub-diff span[data-change=add]{color:var(--ui-green);background:color-mix(in srgb,var(--ui-green) 8%,transparent)}.hub-diff span[data-change=remove]{color:var(--ui-orange);background:color-mix(in srgb,var(--ui-orange) 8%,transparent)}
.hub-document-link>button,.hub-external-link{border:0;background:none;color:var(--ui-accent);font:inherit;cursor:pointer;padding:0;text-decoration:none;display:inline;text-align:inherit}.hub-document-link>button:hover,.hub-external-link:hover{text-decoration:underline}
.hub-document-dialog{width:min(1000px,94vw);max-height:90vh;margin:auto;padding:20px;border:1px solid var(--ui-stroke-tertiary);border-radius:16px;background:var(--ui-surface-background);color:var(--ui-text-primary);overflow:auto;box-shadow:0 12px 80px #0004}.hub-document-dialog::backdrop{background:#0008}.hub-document-dialog header{display:flex;justify-content:space-between;align-items:center;gap:16px;position:sticky;top:-20px;background:var(--ui-surface-background);padding:12px 0;z-index:1}.hub-document-dialog header button{border:0;background:none;color:inherit;cursor:pointer;font-size:24px}.hub-document-path{font-size:11px;color:var(--ui-text-tertiary);overflow-wrap:anywhere}.hub-document-content{line-height:1.65;font-size:14px;white-space:normal}.hub-document-content pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:none}.hub-document-content table{max-width:100%;overflow:auto;display:block}
.hub-changed-files{border:1px solid var(--ui-stroke-tertiary);border-radius:16px;margin:16px 0 8px;overflow:hidden;font-size:13px}.hub-changed-files>header{padding:16px 18px;border-bottom:1px solid var(--ui-stroke-tertiary);display:flex;align-items:center;justify-content:space-between;gap:12px}.hub-diff-counts{white-space:nowrap;font-family:ui-monospace,Consolas,monospace;font-size:12px}.hub-diff-counts [data-change=add]{color:var(--ui-green)}.hub-diff-counts [data-change=remove]{color:var(--ui-orange)}.hub-changed-file>summary{cursor:pointer;padding:10px 18px;display:flex;align-items:center;justify-content:space-between;gap:16px}.hub-changed-file>summary>span:first-child{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.hub-changed-file>summary:hover{background:var(--ui-control-hover-background)}.hub-changed-file pre{margin:0;padding:12px 18px;overflow:auto;max-height:400px;font-size:12px;line-height:1.6;white-space:pre;tab-size:2}.hub-show-files{border:0;background:none;color:inherit;padding:10px 18px;cursor:pointer}.hub-message-body li>p{margin-bottom:0}
@media(max-width:700px){.hub-detail.hub-conversation{padding:8px}.hub-message[data-role=user]{margin-left:8%}.hub-composer-footer small{display:none}.hub-copy-message{opacity:1}}
@media(prefers-reduced-motion:reduce){.hub-copy-message{transition:none}}
`

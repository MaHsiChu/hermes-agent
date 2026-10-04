"""Request-owned prompt media and atomic send admission never borrow a peer's staging."""
import base64
import io
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from tui_gateway import server


def image_input():
    out = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(out, format='PNG')
    return {'filename': '../../outside.jpg', 'content_base64': base64.b64encode(out.getvalue()).decode()}


@pytest.fixture
def native(tmp_path, monkeypatch):
    sid = 'owned-media'
    session = dict(agent=SimpleNamespace(clear_interrupt=lambda: None), running=True,
                   history=[], history_lock=threading.RLock(), history_version=0,
                   attached_images=['desktop.png'], profile_home=str(tmp_path),
                   session_key=sid, transport=None)
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setattr(server, '_ensure_active_session_slot', lambda *a: None)
    monkeypatch.setattr(server, '_session_uses_compute_host', lambda *a: False)
    monkeypatch.setattr(server, '_typed_stop_phrase_response', lambda *a: None)
    return sid, session


def test_request_images_are_validated_before_mutation_and_queue_keeps_ownership(native, tmp_path, monkeypatch):
    sid, session = native
    call = server._methods['prompt.submit']
    valid = image_input()
    invalid = {**valid, 'content_base64': base64.b64encode(b'not an image').decode()}
    for payload in (None, [valid, invalid], [valid] * 6):
        result = call(1, {'session_id': sid, 'text': 'remote', 'queued': True, 'image_inputs': payload})
        assert 'error' in result
        assert session['attached_images'] == ['desktop.png']
        assert session['history'] == [] and not session.get('queued_prompt')
        assert not list(tmp_path.rglob('*.png'))
    for text, images in [('remote image', [valid]), ('remote text', [])]:
        result = call(1, {'session_id': sid, 'text': text, 'queued': True, 'image_inputs': images})
        assert result['result']['status'] == 'queued'
        images.clear()
    assert session['attached_images'] == ['desktop.png']
    first, second = session['queued_prompt'], session['queued_prompts'][0]
    assert len(first['image_paths']) == 1 and Path(first['image_paths'][0]).is_file()
    assert second['image_paths'] == []
    seen = []
    monkeypatch.setattr(server, '_run_prompt_submit', lambda *a, **kw: seen.append(kw['image_paths']))
    for _ in range(2):
        session['running'] = False
        server._drain_queued_prompt('drain', sid, session)
    assert seen == [first['image_paths'], []]
    assert session['attached_images'] == ['desktop.png']


@pytest.mark.parametrize("reject_if_busy", [True, False])
def test_send_rechecks_busy_at_atomic_claim(native, monkeypatch, reject_if_busy):
    sid, session = native
    session['running'] = False
    original = server._lock_in_submit_turn
    def competing_peer(*args, **kwargs):
        # Peer wins after the optimistic busy check, before actual admission.
        with session['history_lock']:
            session['running'] = True
            session['inflight_turn'] = {'user': 'desktop turn'}
        return original(*args, **kwargs)
    monkeypatch.setattr(server, '_lock_in_submit_turn', competing_peer)
    result = server._methods['prompt.submit'](1, {
        'session_id': sid, 'text': 'remote', 'queued': True,
        'image_inputs': [], 'reject_if_busy': reject_if_busy})
    if reject_if_busy:
        assert result['error']['code'] == 4091
        assert not session.get('queued_prompt')
    else:
        assert result['result']['status'] == 'queued'
        assert session['queued_prompt']['image_paths'] == []
    assert session['inflight_turn']['user'] == 'desktop turn'
    assert session['attached_images'] == ['desktop.png']


def test_owned_media_stays_in_profile_and_cancel_never_deletes_legacy(native, tmp_path, monkeypatch):
    from agent.secret_scope import is_multiplex_active, set_multiplex_active
    sid, session = native
    previous = is_multiplex_active()
    set_multiplex_active(True)
    try:
        for profile in ('A', 'B', 'A'):
            home = tmp_path / profile
            session['profile_home'] = str(home)
            response = server._methods['prompt.submit'](1, {
                'session_id': sid, 'text': 'remote', 'queued': True, 'image_inputs': [image_input()]})
            assert response['result']['status'] == 'queued'
            queued_path = Path(session['queued_prompt']['image_paths'][0])
            assert queued_path.is_relative_to(home / 'images') and queued_path.is_file()
            legacy = home / 'images' / 'prompt-request-user-folder' / 'desktop.png'
            legacy.parent.mkdir(exist_ok=True); legacy.write_bytes(b'desktop-owned')
            server._discard_request_images(session, [str(legacy)])
            assert legacy.exists()
            monkeypatch.setattr(server, '_clear_pending', lambda *a: None)
            server._interrupt_session_turn(sid, session)
            assert not queued_path.exists() and legacy.exists()
            assert session['attached_images'] == ['desktop.png']
            session['running'] = True
            session['_turn_cancel_requested'] = False
    finally:
        set_multiplex_active(previous)


@pytest.mark.parametrize('isolated', [False, True])
def test_idle_owned_paths_reach_turn_without_consuming_local(native, monkeypatch, isolated):
    sid, session = native
    session['running'] = False
    seen = []
    finished = threading.Event()
    monkeypatch.setattr(server, '_session_uses_compute_host', lambda *a: isolated)
    monkeypatch.setattr(server, '_persist_session_row_for_submit', lambda *a: None)
    monkeypatch.setattr(server, '_start_agent_build', lambda *a: None)
    monkeypatch.setattr(server, '_wait_agent_for_prompt', lambda *a: None)
    def runner(*args, **kw):
        seen.append(list(kw['image_paths']))
        server._release_request_image_batches(session, kw['image_paths'])
        finished.set()
        return server._ok(1, {'status':'streaming'})
    monkeypatch.setattr(server, '_run_prompt_submit', runner)
    monkeypatch.setattr(server, '_submit_prompt_to_compute_host', runner)
    for payload in ([image_input()], []):
        finished.clear()
        session['running'] = False
        response = server._methods['prompt.submit'](1, {'session_id':sid,'text':'remote', 'image_inputs':payload, 'reject_if_busy':True})
        assert response['result']['status'] == 'streaming'
        assert finished.wait(5)
        if not isolated:
            session['_run_thread'].join(5)
        assert session['attached_images'] == ['desktop.png']
    assert len(seen[0]) == 1 and Path(seen[0][0]).is_file()
    assert seen[1] == []


@pytest.mark.parametrize('adopted', [False, True])
def test_compute_lifetime_releases_only_unadopted_request_files(native, monkeypatch, adopted):
    sid, session = native
    paths, error = server._prepare_prompt_images(1, session, {'image_inputs':[image_input()]})
    assert error is None
    callbacks = []
    monkeypatch.setattr(server, '_get_compute_host_supervisor', lambda *a: SimpleNamespace(
        submit_turn=lambda frame, on_complete: callbacks.append(on_complete)))
    monkeypatch.setattr(server, '_on_compute_host_turn_done', lambda *a: None)
    response = server._submit_prompt_to_compute_host(1, sid, session, 'remote', image_paths=paths)
    assert response['result']['status'] == 'streaming'
    assert Path(paths[0]).exists()
    callbacks[0]({'type':'turn.end','request_images_adopted':adopted})
    assert Path(paths[0]).exists() is adopted
    assert not session.get('_prompt_image_batches')
    assert session['attached_images'] == ['desktop.png']


@pytest.mark.parametrize('dispatch', ['inline', 'queue'])
def test_final_startup_refusal_discards_owned_images(native, monkeypatch, dispatch):
    """A known refusal after admission must not leave unused durable image assets."""
    sid, session = native
    paths, error = server._prepare_prompt_images(1, session, {'image_inputs': [image_input()]})
    assert error is None and Path(paths[0]).is_file()
    admitted = []
    admit = server._admit_prompt_turn
    def record_admission(*args, **kwargs):
        result = admit(*args, **kwargs)
        admitted.append(result)
        return result
    monkeypatch.setattr(server, '_admit_prompt_turn', record_admission)
    monkeypatch.setattr(server, '_wait_agent_for_prompt', lambda *args: None)
    started = []
    def refuse_start(*args, **kwargs):
        started.append(kwargs['name'])
        return None  # backend retires between image admission and worker startup
    monkeypatch.setattr(server, '_start_session_work', refuse_start)
    if dispatch == 'inline':
        server._run_after_agent_ready(1, sid, session, 'remote', None, None, image_paths=paths)
    else:
        server._enqueue_prompt(session, 'remote', None, image_paths=paths)
        session['running'] = False
        server._drain_queued_prompt(1, sid, session)
    assert admitted and admitted[0][0] == paths
    assert started == [f'prompt-turn-{sid}']
    assert not Path(paths[0]).exists()
    assert not session.get('_prompt_image_batches')
    assert session['attached_images'] == ['desktop.png']
    assert session['running'] is False

import pytest


def test_authorized_attachment_paths_reject_escape_and_enforce_size(tmp_path):
    from remote_control.attachments import authorized_image
    allowed=tmp_path/'allowed';allowed.mkdir()
    inside=allowed/'image.png';inside.write_bytes(b'12345')
    outside=tmp_path/'secret.png';outside.write_bytes(b'private')
    assert authorized_image(inside,[allowed],10)==('image.png',b'12345')
    with pytest.raises(ValueError,match='outside'):
        authorized_image(allowed/'..'/'secret.png',[allowed],10)
    with pytest.raises(ValueError,match='limit'):
        authorized_image(inside,[allowed],3)


def test_journal_reconnect_replays_unsent_revision(tmp_path):
    from remote_control.bridge_state import BridgeState
    state=BridgeState(tmp_path/'journal.sqlite')
    # Crash window: normalization committed, no network outbox written yet.
    original=state.revise('s',[{'id':'m','content':'changed','ordinal':1}])
    restarted=BridgeState(tmp_path/'journal.sqlite')
    assert restarted.message_rows('s')==original


def test_history_redaction_removes_secret_fields_and_token_urls():
    from remote_control.security import redact
    result=redact({'password':'sensitive','input':{'api_key':'key','safe':'ok'},'content':'Authorization: Bearer abc.def token=xyz OPENAI_API_KEY=sk-test https://host/?token=query-secret&safe=ok'})
    assert result['input']=={'safe':'ok'}
    assert not any(secret in str(result) for secret in ('sensitive','abc.def','xyz','sk-test','query-secret'))
    assert 'safe=ok' in result['content']
    assert redact('prefix-token-tail = value; safe=token=hidden&next=ok')=='prefix-token-tail = [redacted]; safe=token=[redacted]&next=ok'
    assert redact('plain: https://host/?API-KEY=hidden&safe=yes')=='plain: https://host/?API-KEY=[redacted]&safe=yes'


def test_repeated_sensitive_words_without_assignment_do_not_stall_redaction():
    import time
    from remote_control.security import redact
    text='token'*20000
    started=time.perf_counter()
    assert redact(text)==text
    # Five seconds is deliberately generous for a100kB string; the previous
    # overlapping matcher takes quadratic time even though nothing is secret.
    assert time.perf_counter()-started<5

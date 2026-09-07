from burnlens_cloud.funnel import FIRST_SYNC, WORKSPACE_CREATED, emit


def test_funnel_emit_logs_event_without_payload(caplog):
    caplog.set_level("INFO", logger="burnlens.funnel")
    emit(WORKSPACE_CREATED, workspace_id="ws-test")
    assert "funnel.workspace_created" in caplog.text
    assert "ws-test" in caplog.text
    assert "prompt" not in caplog.text.lower()


def test_funnel_first_sync_name_is_stable():
    assert FIRST_SYNC == "first_sync"

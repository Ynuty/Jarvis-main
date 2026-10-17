"""Живое подключение: проверяем без сети, что клиент физически не может ничего отправить."""

import pytest

telethon = pytest.importorskip("telethon")
from telethon.tl import functions, types  # noqa: E402

from jarvis.secrets import MemoryStore  # noqa: E402
from jarvis.sources.telegram_live import (  # noqa: E402
    KEY_API_HASH,
    KEY_API_ID,
    ReadOnlyViolation,
    TelegramLiveSource,
    check_read_only,
)

SELF = types.InputPeerSelf()


@pytest.mark.parametrize(
    "request_",
    [
        functions.messages.SendMessageRequest(peer=SELF, message="x"),
        functions.messages.EditMessageRequest(peer=SELF, id=1, message="x"),
        functions.messages.DeleteMessagesRequest(id=[1]),
        functions.messages.ForwardMessagesRequest(from_peer=SELF, id=[1], to_peer=SELF),
        functions.messages.ReadHistoryRequest(peer=SELF, max_id=0),       # не отмечаем «прочитано»
        functions.account.UpdateStatusRequest(offline=False),              # не светим «в сети»
        functions.messages.SetTypingRequest(peer=SELF, action=types.SendMessageTypingAction()),
        functions.messages.SendReactionRequest(peer=SELF, msg_id=1),
        functions.InvokeWithLayerRequest(layer=1, query=functions.messages.SendMessageRequest(peer=SELF, message="x")),
    ],
)
def test_write_requests_are_blocked(request_):
    with pytest.raises(ReadOnlyViolation):
        check_read_only(request_)


@pytest.mark.parametrize(
    "request_",
    [
        functions.messages.GetHistoryRequest(peer=SELF, offset_id=0, offset_date=None, add_offset=0,
                                             limit=10, max_id=0, min_id=0, hash=0),
        functions.messages.GetDialogsRequest(offset_date=None, offset_id=0, offset_peer=SELF, limit=10, hash=0),
        functions.auth.SendCodeRequest(phone_number="+0", api_id=1, api_hash="x", settings=types.CodeSettings()),
        functions.auth.LogOutRequest(),
    ],
)
def test_read_and_login_requests_pass(request_):
    check_read_only(request_)


def test_client_blocks_send_before_network():
    src = TelegramLiveSource(MemoryStore({KEY_API_ID: "1", KEY_API_HASH: "abc"}))
    client = src._get_client()
    try:
        with pytest.raises(ReadOnlyViolation):
            src._run(client(functions.messages.SendMessageRequest(peer=SELF, message="x")))
    finally:
        src._loop.close()


def test_requires_own_api_credentials():
    src = TelegramLiveSource(MemoryStore())
    assert not src.has_api_credentials()
    with pytest.raises(RuntimeError, match="my.telegram.org"):
        src._get_client()
    src.save_api_credentials(12345, " hash ")
    assert src.store.get(KEY_API_HASH) == "hash"
    src._loop.close()

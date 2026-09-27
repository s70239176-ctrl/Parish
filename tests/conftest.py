import importlib.util
import sys
from datetime import datetime as _real_datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mock_genlayer  # noqa: E402

sys.modules["genlayer"] = mock_genlayer

CONTRACT_PATH = Path(__file__).resolve().parent.parent / "contracts" / "parish_markets.py"


class _FakeDateTime(_real_datetime):
    """Lets tests pin `datetime.now(timezone.utc)` to a fixed unix time."""

    _now_unix = 1_700_000_000

    @classmethod
    def now(cls, tz=None):
        return _real_datetime.fromtimestamp(cls._now_unix, tz)


def _load_contract_module():
    spec = importlib.util.spec_from_file_location("parish_markets", CONTRACT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.datetime = _FakeDateTime
    return module


@pytest.fixture()
def clock():
    """Fixture exposing a settable fake wall clock as unix seconds."""
    _FakeDateTime._now_unix = 1_700_000_000
    class Clock:
        def set(self, unix_time: int):
            _FakeDateTime._now_unix = unix_time
        def advance(self, seconds: int):
            _FakeDateTime._now_unix += seconds
        def get(self) -> int:
            return _FakeDateTime._now_unix
    return Clock()


@pytest.fixture()
def gl():
    mock_genlayer.TRANSFERS.clear()
    mock_genlayer.gl.nondet.web._responses.clear()
    mock_genlayer.gl.nondet.web.calls.clear()
    mock_genlayer.gl.nondet._prompt_error = None
    mock_genlayer.gl.nondet.prompts.clear()
    mock_genlayer.gl.message.sender_address = mock_genlayer.Address("0x" + "1" * 40)
    mock_genlayer.gl.message.value = mock_genlayer.u256(0)
    return mock_genlayer.gl


@pytest.fixture()
def contract_module(gl):
    return _load_contract_module()


@pytest.fixture()
def contract(contract_module):
    return contract_module.ParishMarkets("1000000000000000000")


@pytest.fixture()
def as_user(gl):
    def _switch(address_hex: str, value_wei: int = 0):
        gl.message.sender_address = mock_genlayer.Address(address_hex)
        gl.message.value = mock_genlayer.u256(value_wei)
    return _switch

"""
A minimal in-process stand-in for the `genlayer` SDK so ParishMarkets' pure
Python logic (lifecycle, accounting, evidence handling) can be unit tested
without a live GenLayer node/validator set.

It intentionally does NOT model true multi-validator non-determinism: each
`gl.eq_principle.strict_eq(fn)` call just runs `fn()` once in-process. What it
does let tests control precisely is: current sender/value, current wall
clock, and the behavior of `gl.nondet.web.get` / `gl.nondet.exec_prompt`
(success, HTTP status, or raising to simulate a failed fetch) so contract-side
retry/fallback/consensus-failure handling can be exercised directly.
"""
from __future__ import annotations

import types
import typing


class Address:
    def __init__(self, value: str):
        self._value = value.lower()

    def __str__(self) -> str:
        return self._value

    def __eq__(self, other) -> bool:
        return isinstance(other, Address) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)


class u256(int):
    def __new__(cls, value=0):
        value = int(value)
        if value < 0:
            raise ValueError("u256 cannot be negative")
        return super().__new__(cls, value)

    def __add__(self, other):
        return u256(int(self) + int(other))

    def __sub__(self, other):
        return u256(int(self) - int(other))

    def __mul__(self, other):
        return u256(int(self) * int(other))

    def __floordiv__(self, other):
        return u256(int(self) // int(other))


class TreeMap(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


class DynArray(list):
    pass


def allow_storage(cls):
    return cls


class _Message:
    def __init__(self):
        self.sender_address = Address("0x" + "1" * 40)
        self.value = u256(0)


class _WebResponse:
    def __init__(self, body: bytes, status_code: int = 200):
        self.body = body
        self.status_code = status_code


class _NondetWeb:
    """Test-controlled fetch behavior, keyed by URL."""

    def __init__(self):
        self._responses: dict[str, object] = {}
        self.calls: list[str] = []

    def set_response(self, url: str, body: bytes = b"", status_code: int = 200):
        self._responses[url] = _WebResponse(body, status_code)

    def set_failure(self, url: str, error: Exception | None = None):
        self._responses[url] = error or Exception("simulated fetch failure")

    def get(self, url: str):
        self.calls.append(url)
        result = self._responses.get(url)
        if result is None:
            raise Exception(f"no mock response configured for {url}")
        if isinstance(result, Exception):
            raise result
        return result


class _Nondet:
    def __init__(self):
        self.web = _NondetWeb()
        self._prompt_response = {"outcome": "UNRESOLVED", "reasoning": ""}
        self._prompt_error: Exception | None = None
        self.prompts: list[str] = []

    def set_prompt_response(self, response: dict):
        self._prompt_error = None
        self._prompt_response = response

    def set_prompt_failure(self, error: Exception | None = None):
        self._prompt_error = error or Exception("simulated LLM failure")

    def exec_prompt(self, prompt: str, response_format: str = "json"):
        self.prompts.append(prompt)
        if self._prompt_error is not None:
            raise self._prompt_error
        return self._prompt_response


class _EqPrinciple:
    """By default just runs fn() once (single in-process "validator"). Tests
    that need to simulate the consensus layer itself failing — validators
    genuinely disagreeing / no majority — rather than fn()'s own content
    failing, use set_failure() to make the next N calls raise regardless of
    what fn() would have returned."""

    def __init__(self):
        self._fail_remaining = 0
        self._fail_error: Exception | None = None
        self.call_count = 0

    def set_failure(self, times: int = 1, error: Exception | None = None):
        self._fail_remaining = times
        self._fail_error = error or Exception("validators did not reach a majority")

    def strict_eq(self, fn):
        self.call_count += 1
        if self._fail_remaining > 0:
            self._fail_remaining -= 1
            raise self._fail_error
        return fn()


class _WriteDecorator:
    def __call__(self, fn):
        fn._is_write = True
        return fn

    @staticmethod
    def payable(fn):
        fn._is_write = True
        fn._is_payable = True
        return fn


class _Public:
    write = _WriteDecorator()

    @staticmethod
    def view(fn):
        fn._is_view = True
        return fn


# Records every simulated outbound value transfer (e.g. claim() payouts) so
# tests can assert on recipient/amount without a real EVM call.
TRANSFERS: list[dict] = []


class _ContractProxy:
    def __init__(self, address):
        self.address = address

    def __getattr__(self, name):
        def _call(*args, **kwargs):
            TRANSFERS.append({"method": name, "address": self.address, "args": args, "kwargs": kwargs})
            return None
        return _call


class _EvmModule:
    @staticmethod
    def contract_interface(cls):
        return _ContractProxy


class Contract:
    """Auto-initializes declared TreeMap/DynArray storage fields to empty
    containers before the subclass's own __init__ runs, mirroring how real
    GenLayer contract storage fields come into existence."""

    def __new__(cls, *args, **kwargs):
        obj = object.__new__(cls)
        annotations: dict = {}
        for klass in reversed(cls.__mro__):
            annotations.update(getattr(klass, "__annotations__", {}))
        for name, annotation in annotations.items():
            origin = typing.get_origin(annotation)
            if origin is TreeMap:
                setattr(obj, name, TreeMap())
            elif origin is DynArray:
                setattr(obj, name, DynArray())
        return obj


class GenLayerSDK(types.SimpleNamespace):
    pass


def build_gl():
    gl = GenLayerSDK()
    gl.message = _Message()
    gl.nondet = _Nondet()
    gl.eq_principle = _EqPrinciple()
    gl.public = _Public()
    gl.evm = _EvmModule()
    gl.Contract = Contract
    return gl


gl = build_gl()

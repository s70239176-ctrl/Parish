"""
Unit tests for contracts/parish_markets.py, run against the in-process mock
SDK in mock_genlayer.py (see its module docstring for what it does and does
not simulate). Covers the steward-requested scenarios: malformed evidence
URLs, failed fetches, evidence history (no overwrite), consensus/LLM
failure, unresolved markets, zero-payout claims, trapped pool balances, and
the full stake -> close -> resolve -> claim flow.
"""
import json

import pytest

import mock_genlayer as mg

CREATOR = "0x" + "1" * 40
ALICE = "0x" + "2" * 40
BOB = "0x" + "3" * 40
MIN_STAKE = 10**18  # 1 GEN, matches the contract fixture's min_stake_wei


def make_market(contract, as_user, clock, closes_in=600, mode="WEB", source="https://example.com/q"):
    as_user(CREATOR)
    market_id = contract.create_market(
        "Will this test pass on the first try?", "Resolves YES if the suite is green.",
        "Civic", "CI", source, mode, str(clock.get() + closes_in),
    )
    return market_id


def stake(contract, as_user, market_id, who, side, amount=MIN_STAKE):
    as_user(who, amount)
    contract.stake(market_id, side)


class TestMarketLifecycle:
    def test_create_market_rejects_close_time_under_five_minutes(self, contract, as_user, clock):
        as_user(CREATOR)
        with pytest.raises(Exception, match="five minutes"):
            contract.create_market("Is five minutes enforced?", "Resolves YES if so.",
                "Civic", "CI", "", "WEB", str(clock.get() + 60))

    def test_stake_rejected_after_close(self, contract, as_user, clock):
        market_id = make_market(contract, as_user, clock, closes_in=300)
        clock.advance(301)
        with pytest.raises(Exception, match="closed to new stakes"):
            stake(contract, as_user, market_id, ALICE, "YES")

    def test_cancel_market_before_any_stakes(self, contract, as_user, clock):
        market_id = make_market(contract, as_user, clock)
        as_user(CREATOR)
        contract.cancel_market(market_id)
        market = json.loads(contract.get_market(market_id))
        assert market["status"] == "CANCELLED"

    def test_cancel_market_rejected_once_staked(self, contract, as_user, clock):
        market_id = make_market(contract, as_user, clock)
        stake(contract, as_user, market_id, ALICE, "YES")
        as_user(CREATOR)
        with pytest.raises(Exception, match="cannot be cancelled"):
            contract.cancel_market(market_id)

    def test_cancel_market_only_by_creator(self, contract, as_user, clock):
        market_id = make_market(contract, as_user, clock)
        as_user(ALICE)
        with pytest.raises(Exception, match="Only the creator"):
            contract.cancel_market(market_id)


class TestEvidenceHistory:
    def test_malformed_url_is_rejected_without_fetching(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock)
        as_user(ALICE)
        with pytest.raises(Exception, match="http"):
            contract.submit_evidence(market_id, "ftp://not-a-web-url.example", "note")
        assert gl.nondet.web.calls == []

    def test_failed_fetch_is_recorded_not_raised(self, contract, as_user, clock, gl, contract_module):
        market_id = make_market(contract, as_user, clock)
        gl.nondet.web.set_failure("https://dead-link.example/evidence")
        as_user(ALICE)
        result = json.loads(contract.submit_evidence(market_id, "https://dead-link.example/evidence", "it's down"))
        assert result["verified"] is False
        history = json.loads(contract.get_evidence_history(market_id))
        assert len(history) == 1
        assert history[0]["fetch_error"] != ""
        assert history[0]["verified"] is False
        # The bounded retry loop should have retried up to FETCH_ATTEMPTS times, not once and not forever.
        assert gl.nondet.web.calls.count("https://dead-link.example/evidence") == contract_module.FETCH_ATTEMPTS

    def test_multiple_submissions_are_kept_not_overwritten(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock)
        gl.nondet.web.set_response("https://source-one.example", b"first body", 200)
        gl.nondet.web.set_response("https://source-two.example", b"second body", 200)
        as_user(ALICE)
        contract.submit_evidence(market_id, "https://source-one.example", "first")
        contract.submit_evidence(market_id, "https://source-two.example", "second")
        history = json.loads(contract.get_evidence_history(market_id))
        assert [item["url"] for item in history] == ["https://source-one.example", "https://source-two.example"]
        latest = json.loads(contract.get_evidence(market_id))
        assert latest["url"] == "https://source-two.example"

    def test_https_and_status_are_verified_via_consensus_snapshot(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock)
        gl.nondet.web.set_response("https://good.example/page", b"hello world", 200)
        as_user(ALICE)
        contract.submit_evidence(market_id, "https://good.example/page", "looks good")
        entry = json.loads(contract.get_evidence(market_id))
        assert entry["https"] is True
        assert entry["status_code"] == "200"
        assert entry["verified"] is True
        assert len(entry["content_hash"]) == 64  # sha256 hex digest

    def test_non_ok_status_is_not_verified(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock)
        gl.nondet.web.set_response("https://gone.example/page", b"not found", 404)
        as_user(ALICE)
        contract.submit_evidence(market_id, "https://gone.example/page", "check this")
        entry = json.loads(contract.get_evidence(market_id))
        assert entry["verified"] is False

    def test_evidence_history_is_bounded(self, contract, as_user, clock, gl, contract_module):
        market_id = make_market(contract, as_user, clock)
        as_user(ALICE)
        for i in range(contract_module.MAX_EVIDENCE_PER_MARKET):
            url = f"https://many.example/{i}"
            gl.nondet.web.set_response(url, b"x", 200)
            contract.submit_evidence(market_id, url, f"note {i}")
        overflow_url = "https://many.example/overflow"
        gl.nondet.web.set_response(overflow_url, b"x", 200)
        with pytest.raises(Exception, match="full"):
            contract.submit_evidence(market_id, overflow_url, "one too many")


class TestResolutionSafety:
    def test_consensus_failure_falls_back_to_void_not_a_crash(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        stake(contract, as_user, market_id, ALICE, "YES")
        stake(contract, as_user, market_id, BOB, "NO")
        clock.advance(700)
        gl.nondet.web.set_response("https://source.example", b"page body", 200)
        gl.nondet.set_prompt_failure(Exception("the model timed out"))
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"
        market = json.loads(contract.get_market(market_id))
        assert market["status"] == "VOID"

    def test_fetch_failure_short_circuits_to_unresolved_without_calling_the_model(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://unreachable.example")
        clock.advance(700)
        gl.nondet.web.set_failure("https://unreachable.example")
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["outcome"] == "UNRESOLVED"
        assert result["status"] == "VOID"
        assert gl.nondet.prompts == []

    def test_malformed_llm_json_falls_back_to_unresolved(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        clock.advance(700)
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response("not-a-dict")
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"

    def test_cannot_resolve_before_deadline(self, contract, as_user, clock):
        market_id = make_market(contract, as_user, clock, closes_in=600)
        as_user(CREATOR)
        with pytest.raises(Exception, match="before its deadline"):
            contract.resolve(market_id)

    def test_resolve_is_not_replayable(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        stake(contract, as_user, market_id, ALICE, "YES")
        clock.advance(700)
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        as_user(CREATOR)
        contract.resolve(market_id)
        with pytest.raises(Exception, match="already been settled"):
            contract.resolve(market_id)

    def test_trapped_pool_when_winning_side_is_empty(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        # Only NO stakers exist; validators still land on YES.
        stake(contract, as_user, market_id, BOB, "NO")
        clock.advance(700)
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"  # not RESOLVED, so the NO pool isn't trapped
        as_user(BOB)
        contract.claim(market_id)
        assert mg.TRANSFERS[-1]["kwargs"]["value"] == MIN_STAKE


class TestSettlementAccounting:
    def _resolve_yes(self, contract, as_user, clock, gl, market_id, source):
        clock.advance(700)
        gl.nondet.web.set_response(source, b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        as_user(CREATOR)
        contract.resolve(market_id)

    def test_full_flow_stake_close_resolve_claim(self, contract, as_user, clock, gl):
        source = "https://source.example"
        market_id = make_market(contract, as_user, clock, mode="WEB", source=source)
        stake(contract, as_user, market_id, ALICE, "YES", amount=2 * MIN_STAKE)
        stake(contract, as_user, market_id, BOB, "NO", amount=1 * MIN_STAKE)
        clock.advance(700)
        as_user(CREATOR)
        contract.close_if_due(market_id)
        assert json.loads(contract.get_market(market_id))["status"] == "CLOSED"
        self._resolve_yes(contract, as_user, clock, gl, market_id, source)
        market = json.loads(contract.get_market(market_id))
        assert market["status"] == "RESOLVED" and market["outcome"] == "YES"
        as_user(ALICE)
        contract.claim(market_id)
        assert mg.TRANSFERS[-1]["kwargs"]["value"] == 2 * MIN_STAKE + (2 * MIN_STAKE * MIN_STAKE) // (2 * MIN_STAKE)

    def test_zero_payout_claim_raises_cleanly_and_stays_retryable_state(self, contract, as_user, clock, gl):
        source = "https://source.example"
        market_id = make_market(contract, as_user, clock, mode="WEB", source=source)
        stake(contract, as_user, market_id, ALICE, "YES")
        stake(contract, as_user, market_id, BOB, "NO")
        self._resolve_yes(contract, as_user, clock, gl, market_id, source)
        as_user(BOB)
        with pytest.raises(Exception, match="nothing to claim"):
            contract.claim(market_id)
        assert mg.TRANSFERS == []
        # No transfer happened and the position was never marked claimed, so
        # a bogus retry doesn't silently succeed either.
        with pytest.raises(Exception, match="nothing to claim"):
            contract.claim(market_id)

    def test_double_claim_is_rejected(self, contract, as_user, clock, gl):
        source = "https://source.example"
        market_id = make_market(contract, as_user, clock, mode="WEB", source=source)
        stake(contract, as_user, market_id, ALICE, "YES")
        stake(contract, as_user, market_id, BOB, "NO")
        self._resolve_yes(contract, as_user, clock, gl, market_id, source)
        as_user(ALICE)
        contract.claim(market_id)
        with pytest.raises(Exception, match="no unclaimed position"):
            contract.claim(market_id)

    def test_unresolved_market_refunds_original_stakes(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        stake(contract, as_user, market_id, ALICE, "YES", amount=3 * MIN_STAKE)
        stake(contract, as_user, market_id, BOB, "NO", amount=1 * MIN_STAKE)
        clock.advance(700)
        gl.nondet.web.set_failure("https://source.example")
        as_user(CREATOR)
        contract.resolve(market_id)
        as_user(ALICE)
        contract.claim(market_id)
        assert mg.TRANSFERS[-1]["kwargs"]["value"] == 3 * MIN_STAKE
        as_user(BOB)
        contract.claim(market_id)
        assert mg.TRANSFERS[-1]["kwargs"]["value"] == 1 * MIN_STAKE

    def test_abandoned_market_expires_after_grace_period_and_refunds(self, contract, as_user, clock, gl, contract_module):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        stake(contract, as_user, market_id, ALICE, "YES")
        clock.advance(700)  # past the deadline, but nobody ever calls resolve()
        as_user(BOB)
        with pytest.raises(Exception, match="grace period"):
            contract.expire_market(market_id)
        clock.advance(contract_module.RESOLUTION_GRACE_SECONDS)
        contract.expire_market(market_id)
        market = json.loads(contract.get_market(market_id))
        assert market["status"] == "EXPIRED"
        as_user(ALICE)
        contract.claim(market_id)
        assert mg.TRANSFERS[-1]["kwargs"]["value"] == MIN_STAKE

    def test_expired_market_cannot_be_resolved_afterwards(self, contract, as_user, clock, gl, contract_module):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        clock.advance(700 + contract_module.RESOLUTION_GRACE_SECONDS)
        contract.expire_market(market_id)
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        with pytest.raises(Exception, match="already been settled"):
            contract.resolve(market_id)

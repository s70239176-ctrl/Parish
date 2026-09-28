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
                "Civic", "CI", "https://example.com", "WEB", str(clock.get() + 60))

    def test_web_mode_requires_a_primary_source_at_creation(self, contract, as_user, clock):
        as_user(CREATOR)
        with pytest.raises(Exception, match="primary source URL"):
            contract.create_market("Does WEB mode need a source?", "Resolves YES if so.",
                "Civic", "CI", "", "WEB", str(clock.get() + 600))

    def test_hybrid_mode_requires_a_primary_source_at_creation(self, contract, as_user, clock):
        as_user(CREATOR)
        with pytest.raises(Exception, match="primary source URL"):
            contract.create_market("Does HYBRID mode need a source?", "Resolves YES if so.",
                "Civic", "CI", "", "HYBRID", str(clock.get() + 600))

    def test_evidence_mode_does_not_require_a_source_at_creation(self, contract, as_user, clock):
        as_user(CREATOR)
        market_id = contract.create_market("Can EVIDENCE mode skip a source?", "Resolves YES if so.",
            "Civic", "CI", "", "EVIDENCE", str(clock.get() + 600))
        assert json.loads(contract.get_market(market_id))["resolution_mode"] == "EVIDENCE"

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

    def test_evidence_rejected_once_overdue_even_if_still_open(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, closes_in=300)
        clock.advance(301)  # deadline passed, but nobody called close_if_due yet
        assert json.loads(contract.get_market(market_id))["status"] == "OPEN"
        gl.nondet.web.set_response("https://late.example", b"x", 200)
        as_user(ALICE)
        with pytest.raises(Exception, match="before its deadline"):
            contract.submit_evidence(market_id, "https://late.example", "too late")

    def test_evidence_rejected_once_closed(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, closes_in=300)
        clock.advance(301)
        as_user(CREATOR)
        contract.close_if_due(market_id)
        assert json.loads(contract.get_market(market_id))["status"] == "CLOSED"
        gl.nondet.web.set_response("https://late.example", b"x", 200)
        as_user(ALICE)
        with pytest.raises(Exception, match="before its deadline"):
            contract.submit_evidence(market_id, "https://late.example", "too late")


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

    def test_evidence_mode_without_evidence_voids_deterministically(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"
        assert gl.nondet.web.calls == []
        assert gl.nondet.prompts == []

    def test_hybrid_mode_without_source_or_evidence_voids_deterministically(self, contract, as_user, clock, gl):
        # HYBRID normally requires a source at creation; simulate an older
        # market that predates that rule by clearing it directly on the record.
        market_id = make_market(contract, as_user, clock, mode="HYBRID", source="https://placeholder.example")
        stored = contract.markets[market_id]
        stored.primary_source_url = ""
        contract.markets[market_id] = stored
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"
        assert gl.nondet.web.calls == []

    def test_unverified_evidence_is_never_fed_to_the_resolver(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        gl.nondet.web.set_response("http://plain-http.example", b"insecure body", 200)  # not https -> unverified
        as_user(ALICE)
        entry = json.loads(contract.submit_evidence(market_id, "http://plain-http.example", "check this"))
        assert entry["verified"] is False
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        # No verified evidence exists, so this is treated the same as no evidence at all.
        assert result["status"] == "VOID"
        assert gl.nondet.prompts == []

    def test_evidence_content_drift_since_submission_is_not_trusted(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        url = "https://drifting.example/page"
        gl.nondet.web.set_response(url, b"the original, hashed content", 200)
        as_user(ALICE)
        entry = json.loads(contract.submit_evidence(market_id, url, "here's my evidence"))
        assert entry["verified"] is True
        # The page changed after submission — a fresh fetch at resolution time
        # no longer hashes to what was snapshotted, so it must not be trusted.
        gl.nondet.web.set_response(url, b"a completely different body now", 200)
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"
        assert gl.nondet.prompts == []

    def test_evidence_matching_its_submission_hash_is_used(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        url = "https://stable.example/page"
        gl.nondet.web.set_response(url, b"stable content", 200)
        as_user(ALICE)
        contract.submit_evidence(market_id, url, "here's my evidence")
        gl.nondet.set_prompt_response({"outcome": "YES"})
        stake(contract, as_user, market_id, ALICE, "YES")
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "RESOLVED" and result["outcome"] == "YES"
        assert len(gl.nondet.prompts) == 1
        assert "here's my evidence" in gl.nondet.prompts[0]

    def test_consensus_failure_is_retried_then_settles_void(self, contract, as_user, clock, gl, contract_module):
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        gl.eq_principle.set_failure(times=contract_module.CONSENSUS_ATTEMPTS)  # every attempt disagrees
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"
        assert gl.eq_principle.call_count == contract_module.CONSENSUS_ATTEMPTS

    def test_consensus_failure_recovers_within_the_retry_budget(self, contract, as_user, clock, gl, contract_module):
        assert contract_module.CONSENSUS_ATTEMPTS > 1, "test assumes there's room to recover after one failure"
        market_id = make_market(contract, as_user, clock, mode="WEB", source="https://source.example")
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        gl.eq_principle.set_failure(times=1)  # disagree once, then reach consensus
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "RESOLVED" and result["outcome"] == "YES"
        assert gl.eq_principle.call_count == 2


class TestMultiRecordEvidenceResolution:
    """resolve() must draw on more than just the single latest verified
    evidence record: a bounded, deterministically-ordered window of the
    verified history, each re-verified against its submission-time hash."""

    def _submit(self, contract, as_user, gl, market_id, who, url, note, body=b"stable content", status=200):
        gl.nondet.web.set_response(url, body, status)
        as_user(who)
        return json.loads(contract.submit_evidence(market_id, url, note))

    def test_two_verified_records_both_influence_the_resolution_input(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://one.example", "first clue")
        self._submit(contract, as_user, gl, market_id, BOB, "https://two.example", "second clue")
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "RESOLVED"
        assert len(gl.nondet.prompts) == 1
        assert "first clue" in gl.nondet.prompts[0]
        assert "second clue" in gl.nondet.prompts[0]

    def test_earlier_valid_evidence_is_not_ignored_because_a_later_record_exists(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://earliest.example", "earliest clue")
        self._submit(contract, as_user, gl, market_id, BOB, "https://latest.example", "latest clue")
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        contract.resolve(market_id)
        # The presence of a later verified record must not have crowded out the earlier one.
        assert "earliest clue" in gl.nondet.prompts[0]

    def test_drifted_later_evidence_is_excluded_but_earlier_valid_evidence_still_used(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://stable.example", "stable clue", b"original A")
        self._submit(contract, as_user, gl, market_id, BOB, "https://drifting.example", "drifting clue", b"original B")
        # The later record's page changes after submission.
        gl.nondet.web.set_response("https://drifting.example", b"a different body now", 200)
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "RESOLVED"
        assert "stable clue" in gl.nondet.prompts[0]
        assert "drifting clue" not in gl.nondet.prompts[0]

    def test_unverified_evidence_excluded_even_alongside_verified_evidence(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://good.example", "good clue", b"body", 200)
        # Not https -> fails submission-time verification regardless of status.
        self._submit(contract, as_user, gl, market_id, BOB, "http://insecure.example", "bad clue", b"body", 200)
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        contract.resolve(market_id)
        assert "good clue" in gl.nondet.prompts[0]
        assert "bad clue" not in gl.nondet.prompts[0]

    def test_evidence_is_considered_in_deterministic_ascending_order(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://a.example", "alpha")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://b.example", "beta")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://c.example", "gamma")
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        contract.resolve(market_id)
        prompt = gl.nondet.prompts[0]
        assert prompt.index("alpha") < prompt.index("beta") < prompt.index("gamma")

    def test_evidence_considered_is_bounded_independent_of_history_size(self, contract, as_user, clock, gl, contract_module):
        market_id = make_market(contract, as_user, clock, mode="EVIDENCE", source="")
        total = contract_module.MAX_EVIDENCE_CONSIDERED + 3
        for i in range(total):
            self._submit(contract, as_user, gl, market_id, ALICE, f"https://item{i}.example", f"clue-{i}")
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        gl.nondet.web.calls.clear()  # only count fetches made during resolve(), not submission
        as_user(CREATOR)
        contract.resolve(market_id)
        prompt = gl.nondet.prompts[0]
        # Only the most recent MAX_EVIDENCE_CONSIDERED submissions were ever eligible.
        for i in range(total - contract_module.MAX_EVIDENCE_CONSIDERED):
            assert f"clue-{i}" not in prompt
        for i in range(total - contract_module.MAX_EVIDENCE_CONSIDERED, total):
            assert f"clue-{i}" in prompt
        assert len(gl.nondet.web.calls) <= contract_module.MAX_EVIDENCE_CONSIDERED * contract_module.FETCH_ATTEMPTS


class TestHybridRequiresBothSourceAndEvidence:
    """HYBRID must never reach an LLM/validator verdict on the primary source
    alone — it needs a primary source AND at least one still-valid verified
    evidence record, or it settles VOID."""

    def _submit(self, contract, as_user, gl, market_id, who, url, note, body=b"stable content", status=200):
        gl.nondet.web.set_response(url, body, status)
        as_user(who)
        return json.loads(contract.submit_evidence(market_id, url, note))

    def test_source_but_no_evidence_voids(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="HYBRID", source="https://source.example")
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"
        assert gl.nondet.prompts == []

    def test_source_and_only_unverified_evidence_voids(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="HYBRID", source="https://source.example")
        self._submit(contract, as_user, gl, market_id, ALICE, "http://insecure.example", "not https", b"x", 200)
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "VOID"
        assert gl.nondet.prompts == []

    def test_source_and_drifted_evidence_with_no_other_valid_record_voids(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="HYBRID", source="https://source.example")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://drifting.example", "will drift", b"original")
        gl.nondet.web.set_response("https://drifting.example", b"different now", 200)
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        # The primary source alone must NOT be enough for HYBRID to proceed.
        assert result["status"] == "VOID"
        assert gl.nondet.prompts == []

    def test_source_and_one_valid_evidence_record_resolves_normally(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="HYBRID", source="https://source.example")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://evidence.example", "solid clue")
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "RESOLVED" and result["outcome"] == "YES"
        assert "solid clue" in gl.nondet.prompts[0]

    def test_resolves_using_only_the_still_valid_evidence_subset(self, contract, as_user, clock, gl):
        market_id = make_market(contract, as_user, clock, mode="HYBRID", source="https://source.example")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://good.example", "good clue", b"good body")
        self._submit(contract, as_user, gl, market_id, BOB, "http://insecure.example", "unverified clue", b"x")
        self._submit(contract, as_user, gl, market_id, ALICE, "https://drifting.example", "stale clue", b"was this")
        gl.nondet.web.set_response("https://drifting.example", b"now this", 200)  # drifts before resolve
        stake(contract, as_user, market_id, ALICE, "YES")
        gl.nondet.web.set_response("https://source.example", b"content", 200)
        gl.nondet.set_prompt_response({"outcome": "YES"})
        clock.advance(700)
        as_user(CREATOR)
        result = json.loads(contract.resolve(market_id))
        assert result["status"] == "RESOLVED" and result["outcome"] == "YES"
        prompt = gl.nondet.prompts[0]
        assert "good clue" in prompt
        assert "unverified clue" not in prompt
        assert "stale clue" not in prompt


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
        result = json.loads(contract.claim(market_id))
        expected_payout = 2 * MIN_STAKE + (2 * MIN_STAKE * MIN_STAKE) // (2 * MIN_STAKE)
        assert result["payout"] == str(expected_payout)
        assert mg.TRANSFERS[-1]["kwargs"]["value"] == expected_payout
        # The sole winner claimed the entire pool; nothing is left outstanding.
        assert json.loads(contract.get_market(market_id))["winner_pool_remaining"] == "0"
        assert json.loads(contract.get_market(market_id))["loser_pool_remaining"] == "0"

    def test_payout_rounding_dust_is_fully_distributed_not_trapped(self, contract, as_user, clock, gl):
        # 3 winning stakes that don't divide the losing pool evenly, claimed in
        # an arbitrary order: the running-pool accounting must still hand out
        # every last wei, regardless of claim order.
        source = "https://source.example"
        market_id = make_market(contract, as_user, clock, mode="WEB", source=source)
        stake(contract, as_user, market_id, ALICE, "YES", amount=MIN_STAKE)
        stake(contract, as_user, market_id, BOB, "YES", amount=MIN_STAKE)
        winners_c = "0x" + "4" * 40
        stake(contract, as_user, market_id, winners_c, "YES", amount=MIN_STAKE)
        loser = "0x" + "5" * 40
        stake(contract, as_user, market_id, loser, "NO", amount=10 * MIN_STAKE)
        self._resolve_yes(contract, as_user, clock, gl, market_id, source)
        total_paid = 0
        for who in (winners_c, ALICE, BOB):  # deliberately not in stake order
            as_user(who)
            total_paid += int(json.loads(contract.claim(market_id))["payout"])
        assert total_paid == 3 * MIN_STAKE + 10 * MIN_STAKE  # every wei of both pools accounted for, no dust left behind
        market = json.loads(contract.get_market(market_id))
        assert market["winner_pool_remaining"] == "0"
        assert market["loser_pool_remaining"] == "0"

    def test_zero_payout_claim_settles_terminally_without_a_transfer(self, contract, as_user, clock, gl):
        source = "https://source.example"
        market_id = make_market(contract, as_user, clock, mode="WEB", source=source)
        stake(contract, as_user, market_id, ALICE, "YES")
        stake(contract, as_user, market_id, BOB, "NO")
        self._resolve_yes(contract, as_user, clock, gl, market_id, source)
        as_user(BOB)
        result = json.loads(contract.claim(market_id))
        assert result == {"market_id": market_id, "payout": "0", "claimed": True}
        assert mg.TRANSFERS == []
        # Settled terminally (claimed=True) even at zero payout, so it can't be
        # claimed again — but it also didn't need to raise to get there.
        with pytest.raises(Exception, match="no unclaimed position"):
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

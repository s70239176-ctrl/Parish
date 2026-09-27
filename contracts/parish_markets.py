# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json

# Terminal statuses that entitle every position to a full stake refund
# (as opposed to RESOLVED, where the winning side splits the losing pool).
REFUND_STATUSES = ("VOID", "EXPIRED", "CANCELLED")
SETTLED_STATUSES = ("RESOLVED",) + REFUND_STATUSES
# How long after a market's deadline it may sit CLOSED without a resolve()
# call before anyone can force it into a refundable EXPIRED state.
RESOLUTION_GRACE_SECONDS = 7 * 24 * 60 * 60
# Bounds the size of a market's evidence history so it can't grow forever.
MAX_EVIDENCE_PER_MARKET = 50
# How many times a single URL fetch is retried inside a non-deterministic
# block before it is recorded as a failure.
FETCH_ATTEMPTS = 3
# How many times validator consensus (gl.eq_principle.strict_eq) itself is
# retried before resolve() gives up and settles the market VOID rather than
# reverting. This is distinct from FETCH_ATTEMPTS: a fetch can fail inside a
# single nondet() run, but strict_eq itself can also fail outright (e.g. no
# majority agreement across validators), and that needs its own bounded
# retry/fallback so a real consensus failure still reaches a terminal state.
CONSENSUS_ATTEMPTS = 2


@allow_storage
@dataclass
class Market:
    id: str
    creator: Address
    question: str
    rules: str
    category: str
    place: str
    primary_source_url: str
    resolution_mode: str
    closes_at_unix: u256
    created_at_unix: u256
    status: str
    outcome: str
    reasoning: str
    yes_pool: u256
    no_pool: u256
    resolved_at_unix: u256
    winner_pool_remaining: u256
    loser_pool_remaining: u256


@allow_storage
@dataclass
class Position:
    market_id: str
    owner: Address
    yes_amount: u256
    no_amount: u256
    claimed: bool


@allow_storage
@dataclass
class Evidence:
    market_id: str
    index: u256
    author: Address
    url: str
    note: str
    submitted_at_unix: u256
    https: bool
    status_code: u256
    content_hash: str
    verified: bool
    fetch_error: str


@gl.evm.contract_interface
class Recipient:
    class View:
        pass
    class Write:
        pass


class ParishMarkets(gl.Contract):
    min_stake: u256
    market_count: u256
    creator: Address
    markets: TreeMap[str, Market]
    positions: TreeMap[str, Position]
    evidence: TreeMap[str, Evidence]
    evidence_count: TreeMap[str, u256]
    market_ids: DynArray[str]

    def __init__(self, min_stake_wei: str):
        self.min_stake = u256(int(min_stake_wei))
        self.market_count = u256(0)
        self.creator = gl.message.sender_address

    def _now(self) -> u256:
        return u256(int(datetime.now(timezone.utc).timestamp()))

    def _position_key(self, market_id: str, owner: Address) -> str:
        return market_id + ":" + str(owner).lower()

    def _evidence_key(self, market_id: str, index: int) -> str:
        return market_id + ":" + str(index)

    def _is_https(self, url: str) -> bool:
        return url.lower().startswith("https://")

    def _market_json(self, market: Market) -> str:
        return json.dumps({"id": market.id, "creator": str(market.creator), "question": market.question,
            "rules": market.rules, "category": market.category, "place": market.place,
            "primary_source_url": market.primary_source_url, "resolution_mode": market.resolution_mode,
            "closes_at_unix": str(market.closes_at_unix), "created_at_unix": str(market.created_at_unix),
            "status": market.status, "outcome": market.outcome, "reasoning": market.reasoning,
            "yes_pool": str(market.yes_pool), "no_pool": str(market.no_pool),
            "resolved_at_unix": str(market.resolved_at_unix),
            "winner_pool_remaining": str(market.winner_pool_remaining),
            "loser_pool_remaining": str(market.loser_pool_remaining)}, sort_keys=True)

    def _evidence_json(self, item: Evidence) -> dict:
        return {"market_id": item.market_id, "index": str(item.index), "author": str(item.author),
            "url": item.url, "note": item.note, "submitted_at_unix": str(item.submitted_at_unix),
            "https": item.https, "status_code": str(item.status_code), "content_hash": item.content_hash,
            "verified": item.verified, "fetch_error": item.fetch_error}

    def _empty_evidence_json(self, market_id: str) -> dict:
        return {"market_id": market_id, "index": "-1", "author": "", "url": "", "note": "",
            "submitted_at_unix": "0", "https": False, "status_code": "0", "content_hash": "",
            "verified": False, "fetch_error": ""}

    def _evidence_count(self, market_id: str) -> int:
        count_val = self.evidence_count.get(market_id)
        return 0 if count_val is None else int(count_val)

    def _latest_evidence(self, market_id: str):
        count = self._evidence_count(market_id)
        if count == 0:
            return None
        return self.evidence.get(self._evidence_key(market_id, count - 1))

    def _latest_verified_evidence(self, market_id: str):
        """The most recent evidence entry that passed its submission-time
        HTTPS/status/consensus check. Records that failed verification at
        submission time are kept in history for transparency but are never
        fed into a resolution."""
        count = self._evidence_count(market_id)
        for index in range(count - 1, -1, -1):
            item = self.evidence.get(self._evidence_key(market_id, index))
            if item is not None and item.verified:
                return item
        return None

    @gl.public.write
    def create_market(self, question: str, rules: str, category: str, place: str, primary_source_url: str, resolution_mode: str, closes_at_unix: str) -> str:
        if len(question) < 10 or len(question) > 240:
            raise Exception("Question must be between 10 and 240 characters.")
        if len(rules) < 10 or len(rules) > 1000:
            raise Exception("Rules must be between 10 and 1000 characters.")
        if resolution_mode not in ("WEB", "EVIDENCE", "HYBRID"):
            raise Exception("Resolution mode must be WEB, EVIDENCE, or HYBRID.")
        if len(category) > 40 or len(place) > 120 or len(primary_source_url) > 500:
            raise Exception("One of the market fields is too long.")
        if resolution_mode in ("WEB", "HYBRID") and primary_source_url == "":
            raise Exception("WEB and HYBRID markets require a primary source URL.")
        closes = u256(int(closes_at_unix))
        now = self._now()
        if closes < now + u256(300):
            raise Exception("Close time must be at least five minutes from now.")
        market_id = "m-" + str(self.market_count + u256(1))
        self.markets[market_id] = Market(market_id, gl.message.sender_address, question, rules, category, place,
            primary_source_url, resolution_mode, closes, now, "OPEN", "", "", u256(0), u256(0), u256(0), u256(0), u256(0))
        self.market_count = self.market_count + u256(1)
        self.market_ids.append(market_id)
        return market_id

    @gl.public.write
    def cancel_market(self, market_id: str) -> None:
        market = self.markets.get(market_id)
        if market is None:
            raise Exception("Market does not exist.")
        if gl.message.sender_address != market.creator:
            raise Exception("Only the creator can cancel this market.")
        if market.status != "OPEN":
            raise Exception("Only an open market can be cancelled.")
        if market.yes_pool > u256(0) or market.no_pool > u256(0):
            raise Exception("A market with stakes cannot be cancelled; let it expire for a refund instead.")
        market.status = "CANCELLED"
        market.reasoning = "Cancelled by the creator before any stakes were placed."
        market.resolved_at_unix = self._now()
        self.markets[market_id] = market

    @gl.public.write.payable
    def stake(self, market_id: str, side: str) -> None:
        if side not in ("YES", "NO"):
            raise Exception("Side must be YES or NO.")
        market = self.markets.get(market_id)
        if market is None:
            raise Exception("Market does not exist.")
        if market.status != "OPEN" or self._now() >= market.closes_at_unix:
            raise Exception("This market is closed to new stakes.")
        value = gl.message.value
        if value == u256(0) or value < self.min_stake:
            raise Exception("Stake is below the minimum GEN amount.")
        key = self._position_key(market_id, gl.message.sender_address)
        position = self.positions.get(key)
        if position is None:
            position = Position(market_id, gl.message.sender_address, u256(0), u256(0), False)
        if side == "YES":
            market.yes_pool = market.yes_pool + value
            position.yes_amount = position.yes_amount + value
        else:
            market.no_pool = market.no_pool + value
            position.no_amount = position.no_amount + value
        self.markets[market_id] = market
        self.positions[key] = position

    @gl.public.write
    def submit_evidence(self, market_id: str, url: str, note: str) -> str:
        market = self.markets.get(market_id)
        if market is None or market.status != "OPEN" or self._now() >= market.closes_at_unix:
            raise Exception("Evidence can only be submitted to an open market before its deadline.")
        if len(url) < 8 or len(url) > 500 or len(note) < 1 or len(note) > 1000:
            raise Exception("Evidence URL or note has an invalid length.")
        if not (url.startswith("http://") or url.startswith("https://")):
            raise Exception("Evidence URL must start with http:// or https://.")
        count = self._evidence_count(market_id)
        if count >= MAX_EVIDENCE_PER_MARKET:
            raise Exception("This market's evidence history is full.")
        is_https = self._is_https(url)

        def nondet() -> str:
            last_error = ""
            for _ in range(FETCH_ATTEMPTS):
                try:
                    response = gl.nondet.web.get(url)
                    status_code = int(getattr(response, "status_code", 0) or 0)
                    body = response.body[:20000]
                    content_hash = hashlib.sha256(body).hexdigest()
                    verified = is_https and (status_code == 0 or 200 <= status_code < 300)
                    return json.dumps({"status_code": status_code, "content_hash": content_hash,
                        "verified": verified, "fetch_error": ""}, sort_keys=True)
                except Exception as exc:
                    last_error = str(exc)[:200]
            return json.dumps({"status_code": 0, "content_hash": "", "verified": False,
                "fetch_error": last_error or "Could not fetch the evidence URL."}, sort_keys=True)

        snapshot = json.loads(gl.eq_principle.strict_eq(nondet))
        index = u256(count)
        self.evidence[self._evidence_key(market_id, count)] = Evidence(market_id, index,
            gl.message.sender_address, url, note, self._now(), is_https, u256(snapshot["status_code"]),
            snapshot["content_hash"], bool(snapshot["verified"]), snapshot["fetch_error"])
        self.evidence_count[market_id] = u256(count + 1)
        return json.dumps({"market_id": market_id, "index": str(index), "verified": bool(snapshot["verified"])}, sort_keys=True)

    @gl.public.write
    def close_if_due(self, market_id: str) -> None:
        market = self.markets.get(market_id)
        if market is None:
            raise Exception("Market does not exist.")
        if market.status == "OPEN" and self._now() >= market.closes_at_unix:
            market.status = "CLOSED"
            self.markets[market_id] = market

    @gl.public.write
    def expire_market(self, market_id: str) -> None:
        market = self.markets.get(market_id)
        if market is None:
            raise Exception("Market does not exist.")
        if market.status not in ("OPEN", "CLOSED"):
            raise Exception("Market has already been settled.")
        if self._now() < market.closes_at_unix + u256(RESOLUTION_GRACE_SECONDS):
            raise Exception("The resolution grace period has not elapsed yet.")
        market.status = "EXPIRED"
        market.outcome = ""
        market.reasoning = "Resolution window expired without a validator verdict; stakes were refunded."
        market.resolved_at_unix = self._now()
        self.markets[market_id] = market

    def _void_market(self, market: Market, reasoning: str, outcome: str = "") -> None:
        market.outcome = outcome
        market.status = "VOID"
        market.reasoning = reasoning
        market.resolved_at_unix = self._now()

    @gl.public.write
    def resolve(self, market_id: str) -> str:
        market = self.markets.get(market_id)
        if market is None:
            raise Exception("Market does not exist.")
        if self._now() < market.closes_at_unix:
            raise Exception("Market cannot resolve before its deadline.")
        if market.status not in ("OPEN", "CLOSED"):
            raise Exception("Market has already been settled.")
        if market.status == "OPEN":
            market.status = "CLOSED"
        question, rules, mode, source = market.question, market.rules, market.resolution_mode, market.primary_source_url
        latest = self._latest_verified_evidence(market_id)
        evidence_url = "" if latest is None else latest.url
        evidence_note = "" if latest is None else latest.note
        evidence_hash = "" if latest is None else latest.content_hash

        # Enforce that the resolution mode actually has the source material it
        # promises, deterministically (no fetch/LLM needed to know this) — a
        # market can't be steered to UNRESOLVED-by-starvation-of-material and
        # then quietly resolved anyway on whatever happens to be present.
        if mode == "WEB" and source == "":
            self._void_market(market, "Resolution mode is WEB but no primary source URL was ever provided.")
            self.markets[market_id] = market
            return json.dumps({"id": market.id, "status": market.status, "outcome": market.outcome}, sort_keys=True)
        if mode == "EVIDENCE" and evidence_url == "":
            self._void_market(market, "Resolution mode is EVIDENCE but no verified evidence was ever submitted.")
            self.markets[market_id] = market
            return json.dumps({"id": market.id, "status": market.status, "outcome": market.outcome}, sort_keys=True)
        if mode == "HYBRID" and source == "" and evidence_url == "":
            self._void_market(market, "Resolution mode is HYBRID but neither a primary source nor verified evidence was ever provided.")
            self.markets[market_id] = market
            return json.dumps({"id": market.id, "status": market.status, "outcome": market.outcome}, sort_keys=True)

        def nondet() -> str:
            def fetch(target_url: str) -> tuple[str, bool]:
                for _ in range(FETCH_ATTEMPTS):
                    try:
                        return gl.nondet.web.get(target_url).body.decode()[:6000], True
                    except Exception:
                        continue
                return "", False

            def fetch_verified(target_url: str, expected_hash: str) -> tuple[str, bool]:
                # Evidence is only trusted at resolution time if a fresh fetch still
                # hashes to what was recorded at submission time; content that has
                # since changed (or vanished) is treated as unusable, not silently
                # re-trusted from whatever it now says.
                for _ in range(FETCH_ATTEMPTS):
                    try:
                        body = gl.nondet.web.get(target_url).body[:20000]
                        if hashlib.sha256(body).hexdigest() != expected_hash:
                            return "", False
                        return body.decode()[:6000], True
                    except Exception:
                        continue
                return "", False

            primary_text, primary_ok = "", True
            evidence_text, evidence_ok = "", True
            if mode in ("WEB", "HYBRID") and source != "":
                primary_text, primary_ok = fetch(source)
            if mode in ("EVIDENCE", "HYBRID") and evidence_url != "":
                evidence_text, evidence_ok = fetch_verified(evidence_url, evidence_hash)
            required_ok = primary_ok and evidence_ok
            if not required_ok and primary_text == "" and evidence_text == "":
                return json.dumps({"outcome": "UNRESOLVED"}, sort_keys=True)
            prompt = "Resolve this YES/NO prediction market using only supplied material. Return JSON with outcome exactly YES, NO, UNRESOLVED, or INVALID, and concise reasoning. Question: " + question + " Rules: " + rules + " Primary: " + primary_text + " Evidence note: " + evidence_note + " Evidence: " + evidence_text
            try:
                parsed = gl.nondet.exec_prompt(prompt, response_format="json")
                if not isinstance(parsed, dict):
                    raise Exception("Resolver returned invalid JSON.")
                outcome = str(parsed.get("outcome", "UNRESOLVED")).upper()
                if outcome not in ("YES", "NO", "UNRESOLVED", "INVALID"):
                    outcome = "UNRESOLVED"
            except Exception:
                outcome = "UNRESOLVED"
            return json.dumps({"outcome": outcome}, sort_keys=True)

        outcome = "UNRESOLVED"
        last_consensus_error = ""
        for _ in range(CONSENSUS_ATTEMPTS):
            try:
                outcome = json.loads(gl.eq_principle.strict_eq(nondet))["outcome"]
                last_consensus_error = ""
                break
            except Exception as exc:
                last_consensus_error = str(exc)[:200]
        market.resolved_at_unix = self._now()
        if last_consensus_error:
            self._void_market(market, "Validators could not reach consensus on a verdict (" + last_consensus_error + "); stakes were refunded.")
        elif outcome == "YES" and market.yes_pool > u256(0):
            market.outcome, market.status = "YES", "RESOLVED"
            market.reasoning = "Resolved YES by validator consensus from the configured sources."
            market.winner_pool_remaining, market.loser_pool_remaining = market.yes_pool, market.no_pool
        elif outcome == "NO" and market.no_pool > u256(0):
            market.outcome, market.status = "NO", "RESOLVED"
            market.reasoning = "Resolved NO by validator consensus from the configured sources."
            market.winner_pool_remaining, market.loser_pool_remaining = market.no_pool, market.yes_pool
        elif outcome in ("YES", "NO"):
            self._void_market(market, "Validators found " + outcome + ", but the winning side had no stakes; all stakes were refunded.", outcome=outcome)
        else:
            self._void_market(market, "Validators could not reach a YES/NO verdict from the available sources; stakes were refunded.", outcome=outcome)
        self.markets[market_id] = market
        return json.dumps({"id": market.id, "status": market.status, "outcome": market.outcome}, sort_keys=True)

    @gl.public.write
    def claim(self, market_id: str) -> str:
        market = self.markets.get(market_id)
        if market is None or market.status not in SETTLED_STATUSES:
            raise Exception("This market is not ready to claim.")
        key = self._position_key(market_id, gl.message.sender_address)
        position = self.positions.get(key)
        if position is None or position.claimed:
            raise Exception("There is no unclaimed position for this wallet.")
        payout = u256(0)
        if market.status in REFUND_STATUSES:
            payout = position.yes_amount + position.no_amount
        elif market.outcome == "YES" and position.yes_amount > u256(0) and market.winner_pool_remaining > u256(0):
            stake = position.yes_amount
            payout = stake + (stake * market.loser_pool_remaining // market.winner_pool_remaining)
            market.loser_pool_remaining = market.loser_pool_remaining - (payout - stake)
            market.winner_pool_remaining = market.winner_pool_remaining - stake
            self.markets[market_id] = market
        elif market.outcome == "NO" and position.no_amount > u256(0) and market.winner_pool_remaining > u256(0):
            stake = position.no_amount
            payout = stake + (stake * market.loser_pool_remaining // market.winner_pool_remaining)
            market.loser_pool_remaining = market.loser_pool_remaining - (payout - stake)
            market.winner_pool_remaining = market.winner_pool_remaining - stake
            self.markets[market_id] = market
        # A position on the losing side (or a winning side with zero stake) is
        # a legitimate terminal outcome, not an error: mark it claimed with a
        # zero payout so it settles for good instead of being left in an
        # ambiguous unclaimed state that keeps reverting forever.
        position.claimed = True
        self.positions[key] = position
        if payout > u256(0):
            Recipient(gl.message.sender_address).emit_transfer(value=payout)
        return json.dumps({"market_id": market_id, "payout": str(payout), "claimed": True}, sort_keys=True)

    @gl.public.view
    def get_market(self, market_id: str) -> str:
        market = self.markets.get(market_id)
        if market is None:
            raise Exception("Market does not exist.")
        return self._market_json(market)

    @gl.public.view
    def get_position(self, market_id: str, owner: str) -> str:
        position = self.positions.get(market_id + ":" + owner.lower())
        if position is None:
            return json.dumps({"market_id": market_id, "owner": owner, "yes_amount": "0", "no_amount": "0", "claimed": False}, sort_keys=True)
        return json.dumps({"market_id": position.market_id, "owner": str(position.owner), "yes_amount": str(position.yes_amount), "no_amount": str(position.no_amount), "claimed": position.claimed}, sort_keys=True)

    @gl.public.view
    def get_evidence(self, market_id: str) -> str:
        item = self._latest_evidence(market_id)
        if item is None:
            return json.dumps(self._empty_evidence_json(market_id), sort_keys=True)
        return json.dumps(self._evidence_json(item), sort_keys=True)

    @gl.public.view
    def get_evidence_history(self, market_id: str) -> str:
        count = self._evidence_count(market_id)
        items = []
        for index in range(count):
            item = self.evidence.get(self._evidence_key(market_id, index))
            if item is not None:
                items.append(self._evidence_json(item))
        return json.dumps(items, sort_keys=True)

    @gl.public.view
    def list_market_ids(self) -> str:
        encoded = "["
        for index in range(len(self.market_ids)):
            if index > 0:
                encoded = encoded + ","
            encoded = encoded + json.dumps(self.market_ids[index])
        return encoded + "]"

    @gl.public.view
    def get_stats(self) -> str:
        count = int(self.market_count)
        minimum = int(self.min_stake)
        return "{\"market_count\":\"" + str(count) + "\",\"min_stake_wei\":\"" + str(minimum) + "\"}"

    @gl.public.view
    def health(self) -> str:
        return "\"PARISH_OK\""

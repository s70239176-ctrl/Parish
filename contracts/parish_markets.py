# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass
from datetime import datetime, timezone
import json


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
    author: Address
    url: str
    note: str
    submitted_at_unix: u256


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
    market_ids: DynArray[str]

    def __init__(self, min_stake_wei: str):
        self.min_stake = u256(int(min_stake_wei))
        self.market_count = u256(0)
        self.creator = gl.message.sender_address

    def _now(self) -> u256:
        return u256(int(datetime.now(timezone.utc).timestamp()))

    def _position_key(self, market_id: str, owner: Address) -> str:
        return market_id + ":" + str(owner).lower()

    def _market_json(self, market: Market) -> str:
        return json.dumps({"id": market.id, "creator": str(market.creator), "question": market.question,
            "rules": market.rules, "category": market.category, "place": market.place,
            "primary_source_url": market.primary_source_url, "resolution_mode": market.resolution_mode,
            "closes_at_unix": str(market.closes_at_unix), "created_at_unix": str(market.created_at_unix),
            "status": market.status, "outcome": market.outcome, "reasoning": market.reasoning,
            "yes_pool": str(market.yes_pool), "no_pool": str(market.no_pool),
            "resolved_at_unix": str(market.resolved_at_unix)}, sort_keys=True)

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
        closes = u256(int(closes_at_unix))
        now = self._now()
        if closes < now + u256(300):
            raise Exception("Close time must be at least five minutes from now.")
        market_id = "m-" + str(self.market_count + u256(1))
        self.markets[market_id] = Market(market_id, gl.message.sender_address, question, rules, category, place,
            primary_source_url, resolution_mode, closes, now, "OPEN", "", "", u256(0), u256(0), u256(0))
        self.market_count = self.market_count + u256(1)
        self.market_ids.append(market_id)
        return market_id

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
    def submit_evidence(self, market_id: str, url: str, note: str) -> None:
        market = self.markets.get(market_id)
        if market is None or market.status not in ("OPEN", "CLOSED"):
            raise Exception("Evidence can only be submitted to an open or closed market.")
        if len(url) < 8 or len(url) > 500 or len(note) < 1 or len(note) > 1000:
            raise Exception("Evidence URL or note has an invalid length.")
        self.evidence[market_id] = Evidence(market_id, gl.message.sender_address, url, note, self._now())

    @gl.public.write
    def close_if_due(self, market_id: str) -> None:
        market = self.markets.get(market_id)
        if market is None:
            raise Exception("Market does not exist.")
        if market.status == "OPEN" and self._now() >= market.closes_at_unix:
            market.status = "CLOSED"
            self.markets[market_id] = market

    @gl.public.write
    def resolve(self, market_id: str) -> str:
        market = self.markets.get(market_id)
        if market is None:
            raise Exception("Market does not exist.")
        if self._now() < market.closes_at_unix:
            raise Exception("Market cannot resolve before its deadline.")
        if market.status in ("RESOLVED", "VOID"):
            raise Exception("Market has already been settled.")
        if market.status == "OPEN":
            market.status = "CLOSED"
        question, rules, mode, source = market.question, market.rules, market.resolution_mode, market.primary_source_url
        latest = self.evidence.get(market_id)
        evidence_url = "" if latest is None else latest.url
        evidence_note = "" if latest is None else latest.note
        def nondet() -> str:
            primary_text = ""
            evidence_text = ""
            if mode in ("WEB", "HYBRID") and source != "":
                primary_text = gl.nondet.web.get(source).body.decode()[:6000]
            if mode in ("EVIDENCE", "HYBRID") and evidence_url != "":
                evidence_text = gl.nondet.web.get(evidence_url).body.decode()[:6000]
            prompt = "Resolve this YES/NO prediction market using only supplied material. Return JSON with outcome exactly YES, NO, UNRESOLVED, or INVALID, and concise reasoning. Question: " + question + " Rules: " + rules + " Primary: " + primary_text + " Evidence note: " + evidence_note + " Evidence: " + evidence_text
            parsed = gl.nondet.exec_prompt(prompt, response_format="json")
            if not isinstance(parsed, dict):
                raise Exception("Resolver returned invalid JSON.")
            outcome = str(parsed.get("outcome", "UNRESOLVED")).upper()
            if outcome not in ("YES", "NO", "UNRESOLVED", "INVALID"):
                outcome = "UNRESOLVED"
            return json.dumps({"outcome": outcome}, sort_keys=True)
        consensus = json.loads(gl.eq_principle.strict_eq(nondet))
        outcome = consensus["outcome"]
        market.outcome = outcome
        market.reasoning = "Resolved by validator consensus from the configured sources."
        market.resolved_at_unix = self._now()
        market.status = "RESOLVED" if outcome in ("YES", "NO") else "VOID"
        self.markets[market_id] = market
        return json.dumps({"id": market.id, "status": market.status, "outcome": market.outcome}, sort_keys=True)

    @gl.public.write
    def claim(self, market_id: str) -> None:
        market = self.markets.get(market_id)
        if market is None or market.status not in ("RESOLVED", "VOID"):
            raise Exception("This market is not ready to claim.")
        key = self._position_key(market_id, gl.message.sender_address)
        position = self.positions.get(key)
        if position is None or position.claimed:
            raise Exception("There is no unclaimed position for this wallet.")
        position.claimed = True
        self.positions[key] = position
        payout = u256(0)
        if market.status == "VOID":
            payout = position.yes_amount + position.no_amount
        elif market.outcome == "YES" and market.yes_pool > u256(0):
            payout = position.yes_amount + (position.yes_amount * market.no_pool // market.yes_pool)
        elif market.outcome == "NO" and market.no_pool > u256(0):
            payout = position.no_amount + (position.no_amount * market.yes_pool // market.no_pool)
        if payout == u256(0):
            raise Exception("This position has no claimable GEN.")
        Recipient(gl.message.sender_address).emit_transfer(value=payout)

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
        item = self.evidence.get(market_id)
        if item is None:
            return json.dumps({"market_id": market_id, "url": "", "note": "", "author": "", "submitted_at_unix": "0"}, sort_keys=True)
        return json.dumps({"market_id": item.market_id, "url": item.url, "note": item.note, "author": str(item.author), "submitted_at_unix": str(item.submitted_at_unix)}, sort_keys=True)

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

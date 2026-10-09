"""
Flag and scoring engine with per-player attribution.

Two layers (as chosen by the facilitator):
  * Self-check: the player RETRIEVES their earned flag strings over GATT and
    SUBMITS them to earn a personal score.
  * Projector scoreboard: the source of truth — which milestones each player
    caused, with timestamps. Shown live.

Attribution is per BLE address; a player can set a Player Name (callsign) which
is then used on the scoreboard. Flag strings are salted per player so they
cannot be copied between participants.
"""

import hashlib
import time
from . import config


def _flag_string(identity: str, flag_id: str, slug: str) -> str:
    h = hashlib.sha1(
        f"{config.FLAG_SECRET}:{identity}:{flag_id}".encode()
    ).hexdigest()[:6]
    return f"{config.FLAG_PREFIX}{{{slug}-{h}}}"


class Player:
    __slots__ = ("identity", "name", "address", "earned", "verified", "last_seen")

    def __init__(self, identity, name, address):
        self.identity = identity
        self.name = name
        self.address = address
        self.earned = []      # flag_ids in order
        self.verified = set()
        self.last_seen = time.monotonic()


class FlagEngine:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.players = {}          # identity -> Player
        self.addr_name = {}        # address -> chosen name
        self.events = []           # [(t, name, kind, text)] newest first
        self.on_event = None       # optional callback(name, kind, text)

    # --- identity --------------------------------------------------
    def _identity(self, address: str) -> str:
        return self.addr_name.get(address) or address

    def _player(self, address: str) -> Player:
        ident = self._identity(address)
        p = self.players.get(ident)
        if p is None:
            name = self.addr_name.get(address) or self._short_addr(address)
            p = Player(ident, name, address)
            self.players[ident] = p
        p.last_seen = self._clock()
        p.address = address
        return p

    @staticmethod
    def _short_addr(address: str) -> str:
        # "dev_AA_BB_CC_DD_EE_FF" -> "anon-DDEEFF"; otherwise the trailing bits
        a = address.replace("dev_", "").replace("_", ":")
        parts = a.split(":")
        return "anon-" + "".join(parts[-3:]) if len(parts) >= 3 else "anon-" + a

    def name_for(self, address: str) -> str:
        return self.addr_name.get(address) or self._player(address).name

    def set_name(self, address: str, name: str):
        name = (name or "").strip()[:24] or self._short_addr(address)
        old_ident = self._identity(address)
        self.addr_name[address] = name
        # migrate any earlier state (anon -> name)
        if old_ident != name and old_ident in self.players:
            old = self.players.pop(old_ident)
            new = self.players.setdefault(name, Player(name, name, address))
            for fid in old.earned:
                if fid not in new.earned:
                    new.earned.append(fid)
            new.verified |= old.verified
        else:
            p = self.players.setdefault(name, Player(name, name, address))
            p.name = name
        self.add_event(name, "join", f"joined as «{name}»")

    # --- events ----------------------------------------------------
    def add_event(self, name: str, kind: str, text: str):
        self.events.insert(0, (self._clock(), name, kind, text))
        del self.events[60:]
        if self.on_event:
            self.on_event(name, kind, text)

    # --- flags -----------------------------------------------------
    def award(self, address: str, flag_id: str):
        """Award a flag. Returns (is_new, flag_string)."""
        p = self._player(address)
        meta = _FLAG_BY_ID[flag_id]
        fstr = _flag_string(p.identity, flag_id, meta["slug"])
        if flag_id in p.earned:
            return (False, fstr)
        p.earned.append(flag_id)
        self.add_event(p.name, "flag", f"{flag_id} - {meta['title']}")
        return (True, fstr)

    def flags_text(self, address: str) -> bytes:
        p = self._player(address)
        if not p.earned:
            return ("No flags yet. Interact with the pump to earn flags, "
                    "then submit them here.").encode()
        lines = [f"{fid}  {_flag_string(p.identity, fid, _FLAG_BY_ID[fid]['slug'])}"
                 for fid in p.earned]
        return ("\n".join(lines)).encode()

    def submit(self, address: str, text: str) -> bytes:
        p = self._player(address)
        want = (text or "").strip()
        for fid in config.FLAG_IDS:
            meta = _FLAG_BY_ID[fid]
            if _flag_string(p.identity, fid, meta["slug"]) == want:
                if fid not in p.earned:
                    return b"Correct format, but you have not earned that flag yet."
                if fid in p.verified:
                    return f"Already submitted: {fid}.".encode()
                p.verified.add(fid)
                self.add_event(p.name, "verify", f"verified {fid}")
                return f"Correct! {fid} verified. {self._score(p)}".encode()
        return b"Wrong flag (or not yours - flags are personal)."

    def score_text(self, address: str) -> bytes:
        return self._score(self._player(address)).encode()

    @staticmethod
    def _score(p: Player) -> str:
        return f"Score: {len(p.verified)}/{config.FLAG_TOTAL} (earned: {len(p.earned)})"

    # --- for the dashboard ----------------------------------------
    def scoreboard(self):
        rows = []
        for p in self.players.values():
            rows.append({
                "name": p.name,
                "earned": list(p.earned),
                "verified": sorted(p.verified),
                "count": len(p.earned),
                "vcount": len(p.verified),
            })
        rows.sort(key=lambda r: (-r["count"], -r["vcount"], r["name"]))
        return rows

    def recent_events(self, n=12):
        return [
            {"name": nm, "kind": k, "text": tx}
            for (_t, nm, k, tx) in self.events[:n]
        ]


_FLAG_BY_ID = {
    fid: {"slug": slug, "title": title} for (fid, slug, title) in config.FLAGS
}

"""
Web dashboard for the projector (aiohttp).

Serves the static dashboard and pushes state over WebSocket ~10 times/s. Also
receives commands from the dashboard:
  * {"cmd":"reset"}                      -> revive the patient/device
  * {"cmd":"autoreset","value":30|0}     -> auto-reset N s after death (0=off)
  * {"cmd":"debug", "op":..., "value":...} -> test the projection without BLE
"""

import json
import os
from aiohttp import web, WSMsgType

from . import config
from . import model as M

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "web")
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")


class WebServer:
    def __init__(self, model, flags, controller, host="0.0.0.0", port=8080):
        self.model = model
        self.flags = flags
        self.controller = controller
        self.host = host
        self.port = port
        self.clients = set()
        self.auto_reset_s = 0        # 0 = off
        self._runner = None

    # ------------------------------------------------------------
    async def start(self):
        app = web.Application()
        app.router.add_get("/", self._index)
        app.router.add_get("/ws", self._ws)
        app.router.add_static("/static/", WEB_DIR)
        if os.path.isdir(ASSETS_DIR):
            app.router.add_static("/assets/", ASSETS_DIR)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

    async def _index(self, request):
        return web.FileResponse(os.path.join(WEB_DIR, "index.html"))

    # ------------------------------------------------------------
    async def _ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.clients.add(ws)
        try:
            await ws.send_str(json.dumps(self.state()))
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    self._handle_cmd(msg.data)
        finally:
            self.clients.discard(ws)
        return ws

    def _handle_cmd(self, raw):
        try:
            cmd = json.loads(raw)
        except Exception:
            return
        c = cmd.get("cmd")
        if c == "reset":
            self.model.revive()
            self.flags.add_event("facilitator", "reset", "revived the patient")
        elif c == "autoreset":
            self.auto_reset_s = int(cmd.get("value", 0))
        elif c == "debug":
            self._debug(cmd)

    def _debug(self, cmd):
        """Test the projection without BLE (attributed to 'DEMO')."""
        op = cmd.get("op")
        v = float(cmd.get("value", 0))
        m = self.model
        if op == "basal":
            m.set_basal(v)
            self.flags.add_event("DEMO", "cmd", f"[debug] basal {v} U/h")
        elif op == "unlock":
            m.maintenance_unlocked = True
            self.flags.add_event("DEMO", "danger", "[debug] unlock")
        elif op == "maxlimit":
            m.maintenance_unlocked = True
            m.set_max_basal(v)
            self.flags.add_event("DEMO", "danger", f"[debug] max limit {v}")
        elif op == "bolus":
            m.set_bolus(v)
            self.flags.add_event("DEMO", "cmd", f"[debug] bolus {v} U")
        elif op == "silence":
            m.silence_alarms(True)

    # ------------------------------------------------------------
    def state(self) -> dict:
        s = self.model.snapshot()
        s["device_name"] = config.DEVICE_NAME
        s["scoreboard"] = self.flags.scoreboard()
        s["events"] = self.flags.recent_events()
        s["flag_total"] = config.FLAG_TOTAL
        s["flag_defs"] = [{"id": i, "title": t} for (i, _s, t) in config.FLAGS]
        s["auto_reset_s"] = self.auto_reset_s
        return s

    async def broadcast(self):
        if not self.clients:
            return
        payload = json.dumps(self.state())
        dead = []
        for ws in self.clients:
            try:
                await ws.send_str(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

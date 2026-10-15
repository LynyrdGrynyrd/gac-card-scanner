"""Audit 2026-10 P0-12: a hard cap on request body size that counts the bytes actually received.

The older checks read only the Content-Length header. A chunked upload (Transfer-Encoding: chunked) has no Content-Length,
and the handlers then read the whole file into memory before their own size check, so one request could fill RAM or disk.
This pure-ASGI middleware sits in front of the app and answers 413 as soon as the running total passes the limit."""
from starlette.responses import JSONResponse


class TooLarge(Exception):
    pass


class BodyLimit:
    def __init__(self, app, limit, message="Upload is too large (limit 25 MB per photo).", headers=None):
        self.app, self.limit, self.message, self.headers = app, limit, message, headers or {}

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.limit() if callable(self.limit) else self.limit
        for k, v in scope.get("headers") or []:   # a declared size over the limit is refused before reading anything
            if k == b"content-length":
                try:
                    if int(v) > limit: return await self._refuse(scope, receive, send)
                except ValueError:
                    pass
        seen = 0; started = False; over = False

        async def counted_receive():
            nonlocal seen, over
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body") or b"")
                if seen > limit:
                    over = True; raise TooLarge()
            return msg

        async def tracked_send(msg):
            nonlocal started
            if over:   # FastAPI turns an error while parsing the body into its own 400: answer 413 instead, drop the rest
                if msg["type"] == "http.response.start" and not started:
                    started = True; await self._refuse(scope, receive, send)
                return
            if msg["type"] == "http.response.start": started = True
            await send(msg)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except TooLarge:
            if not started: await self._refuse(scope, receive, send)

    async def _refuse(self, scope, receive, send):
        await JSONResponse({"error": self.message}, 413, headers=self.headers | {"Connection": "close"})(scope, receive, send)

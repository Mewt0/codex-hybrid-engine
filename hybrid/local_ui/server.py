from __future__ import annotations

from http.server import HTTPServer
from threading import Thread

from .handlers import LocalUIHandler
from .security import csrf_token


class LocalHTTPServer(HTTPServer):
    def __init__(self, server_address, RequestHandlerClass, *, bridge, controller, token: str):
        super().__init__(server_address, RequestHandlerClass)
        self.bridge = bridge
        self.controller = controller
        self.csrf_token = token
        self.ui_host = server_address[0]
        self.ui_port = self.server_address[1]


class LocalUI:
    def __init__(self, settings, bridge, controller, host: str = "127.0.0.1", port: int = 8765):
        if host != "127.0.0.1":
            raise ValueError("LocalUI only binds 127.0.0.1")
        self.settings = settings
        self.bridge = bridge
        self.controller = controller
        self.host = host
        self.port = port
        self._server: LocalHTTPServer | None = None
        self._thread: Thread | None = None

    def url(self) -> str:
        server = self.server
        host, port = server.server_address[:2]
        return f"http://{host}:{port}/"

    def start(self, block: bool = True) -> str:
        if self._server is None:
            self._server = LocalHTTPServer((self.host, self.port), LocalUIHandler, bridge=self.bridge, controller=self.controller, token=csrf_token())
        url = self.url()
        print(url)
        if block:
            self._server.serve_forever()
        else:
            self._thread = Thread(target=self._server.serve_forever)
            self._thread.start()
        return url

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self._server = None

    @property
    def server(self) -> HTTPServer:
        if self._server is None:
            self._server = LocalHTTPServer((self.host, self.port), LocalUIHandler, bridge=self.bridge, controller=self.controller, token=csrf_token())
        return self._server

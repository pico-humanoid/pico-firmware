"""PICO development desk: local HTTP UI, static assets and a small task API."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import urllib.request
import webbrowser
import catalog

from engine import HERE, LOGS, Manager, ports
import platform_tools as tools

TOKEN = secrets.token_urlsafe(32)
SOURCE_FILES = {
    "App/can_bringup.c": True, "App/can_bringup.h": True,
    "Core/Src/main.c": False, "Core/Src/fdcan.c": False,
    "Core/Src/usart.c": False, "Core/Src/stm32g4xx_it.c": False,
    "CMakeLists.txt": False,
}


def source_files(mode):
    root = tools.project_dir(mode)
    names = dict(SOURCE_FILES)
    names.update({p.relative_to(root).as_posix(): True for p in (root / "App").rglob("*")
                  if p.suffix in (".c", ".h") and p.resolve().is_relative_to(root.resolve())})
    return {name: editable for name, editable in names.items() if (root / name).is_file()}


class Handler(BaseHTTPRequestHandler):
    server_version = "PICO-Desk/1.0"

    def log_message(self, *args):
        pass

    @property
    def manager(self):
        return self.server.manager

    def respond(self, payload, status=200, mime="application/json; charset=utf-8", filename=None):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def allowed(self, mutation=False):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            self.respond({"error": "仅允许本机访问。"}, 403)
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://" + h for h in hosts}:
            self.respond({"error": "不允许跨站访问。"}, 403)
            return False
        if mutation and not secrets.compare_digest(self.headers.get("X-Pico-Token", ""), TOKEN):
            self.respond({"error": "页面已过期，请刷新后重试。"}, 403)
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        parsed = urlsplit(self.path)
        query, path = parse_qs(parsed.query), parsed.path
        try:
            if path == "/api/health":
                return self.respond({"app": "pico-desk", "project": str(tools.ROOT)})
            if path == "/api/state":
                with self.manager.lock:
                    jobs = [j.snapshot() for j in self.manager.jobs.values()][-50:]
                return self.respond({"token": TOKEN, "environment": tools.status(), "ports": ports(),
                                     "profiles": catalog.profiles(), "jobs": jobs})
            if path == "/api/history":
                return self.respond(self.manager.history(query.get("archived", ["0"])[0] == "1"))
            if path == "/api/profiles":
                return self.respond(catalog.profiles())
            if path == "/api/sources":
                return self.respond(source_files(query.get("mode", ["Loopback"])[0]))
            if path == "/api/firmware":
                return self.respond(json.loads((HERE / "data/firmware.json").read_text(encoding="utf-8")))
            if path == "/api/wiring":
                return self.respond(json.loads((HERE / "data/wiring.json").read_text(encoding="utf-8")))
            if path.startswith("/reference/"):
                name = unquote(path[len("/reference/"):])
                file = (HERE / "data" / name).resolve()
                if file.parent != (HERE / "data").resolve() or file.suffix != ".md" or not file.is_file():
                    raise ValueError("找不到此参考文档。")
                return self.respond(file.read_bytes(), mime="text/plain; charset=utf-8")
            if path == "/api/job":
                return self.respond(self.manager.get(query.get("id", [""])[0]).snapshot(
                    True, int(query.get("after", ["0"])[0])))
            if path == "/api/source":
                name = query.get("name", ["App/can_bringup.c"])[0]
                mode = query.get("mode", ["Loopback"])[0]
                sources = source_files(mode)
                if name not in sources:
                    raise ValueError("此文件不在代码工作区中。")
                raw = (tools.project_dir(mode) / name).read_bytes()
                return self.respond({"name": name, "text": raw.decode("utf-8-sig"),
                                     "editable": sources[name], "mode": mode,
                                     "revision": hashlib.sha256(raw).hexdigest()})
            if path == "/api/files":
                files = [{"name": p.name, "bytes": p.stat().st_size}
                         for p in sorted(LOGS.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
                         if p.is_file() and p.suffix in (".csv", ".json")]
                return self.respond(files[:100])
            if path.startswith("/download/"):
                name = unquote(path[len("/download/"):])
                file = (LOGS / name).resolve()
                if file.parent != LOGS.resolve() or not file.is_file() or file.suffix not in (".csv", ".json"):
                    raise ValueError("找不到此日志文件。")
                return self.respond(file.read_bytes(), mime="application/octet-stream", filename=file.name)
            assets = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                      "/style.css": ("style.css", "text/css; charset=utf-8")}
            if path == "/pinout.png":
                image = tools.ROOT / "docs/NUCLEO-G474RE_PA11_PA12.png"
                return self.respond(image.read_bytes(), mime="image/png")
            if path in assets:
                name, mime = assets[path]
                return self.respond((HERE / "static" / name).read_bytes(), mime=mime)
            self.respond({"error": "页面不存在。"}, 404)
        except (OSError, ValueError) as exc:
            self.respond({"error": str(exc)}, 400)

    def do_POST(self):
        if not self.allowed(True):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length < 300000:
                raise ValueError("请求大小不正确。")
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("请求格式不正确。")
            if self.path == "/api/start":
                job = self.manager.start(data.get("kind"), data.get("mode"), data.get("port", ""))
                return self.respond(job.snapshot())
            if self.path == "/api/stop":
                self.manager.stop(data.get("id", ""))
                return self.respond({"ok": True})
            if self.path == "/api/open":
                return self.respond(tools.launch_app(data.get("app"), data.get("mode", "Loopback")))
            if self.path == "/api/profiles":
                with self.manager.lock:
                    if any(j.status == "running" for j in self.manager.jobs.values()):
                        raise ValueError("请先结束当前任务，再修改实验配置。")
                    if data.get("delete"):
                        catalog.delete_profile(data.get("id"))
                        return self.respond({"ok": True})
                    return self.respond(catalog.save_profile(data))
            if self.path == "/api/record":
                return self.respond(catalog.annotate(data) if data.get("id") else catalog.new_record(data))
            if self.path == "/api/source":
                name = data.get("name")
                mode = data.get("mode", "Loopback")
                if not source_files(mode).get(name):
                    raise ValueError("此文件只供查看；硬件初始化请通过 CubeMX 修改。")
                text = data.get("text")
                if not isinstance(text, str) or len(text.encode("utf-8")) > 250000:
                    raise ValueError("源文件内容不正确。")
                with self.manager.lock:
                    if any(j.status == "running" for j in self.manager.jobs.values()):
                        raise ValueError("请先结束当前任务，再保存代码。")
                    file = tools.project_dir(mode) / name
                    raw = file.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != data.get("revision"):
                        raise ValueError("文件已在其他编辑器中修改。请重新载入，避免覆盖。")
                    from datetime import datetime
                    backups = LOGS / "ui_source_backups"
                    backups.mkdir(exist_ok=True)
                    backup = backups / (datetime.now().strftime("%Y%m%d_%H%M%S_%f_") + file.name)
                    backup.write_bytes(raw)
                    file.write_text(text, encoding="utf-8", newline="\n")
                return self.respond({"ok": True, "revision": hashlib.sha256(file.read_bytes()).hexdigest()})
            if self.path == "/api/shutdown":
                with self.manager.lock:
                    if any(j.status == "running" for j in self.manager.jobs.values()):
                        raise ValueError("请先结束当前任务。")
                self.respond({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.respond({"error": "操作不存在。"}, 404)
        except (ValueError, TypeError, OSError) as exc:
            self.respond({"error": str(exc)}, 400)


def make_server(port=8765):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.manager = Manager()
    return httpd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        server = make_server(args.port)
    except OSError:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/health", timeout=2) as response:
                existing = json.load(response)
            if existing.get("app") == "pico-desk" and existing.get("project") == str(tools.ROOT):
                if args.open:
                    webbrowser.open(f"http://127.0.0.1:{args.port}")
                return
        except Exception:
            pass
        raise SystemExit("端口已被其他程序占用，可指定 --port 8766。")
    url = f"http://127.0.0.1:{server.server_port}"
    print("PICO 开发控制台：" + url, flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with server.manager.lock:
            active = [j for j in server.manager.jobs.values() if j.status == "running"]
        for job in active:
            if job.kind != "flash":
                server.manager.stop(job.id)
        server.server_close()


if __name__ == "__main__":
    main()

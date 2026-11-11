# MCP-Anfragen annehmen, prüfen und an die jeweiligen Server weiterleiten.

import asyncio
import logging
import os
import sys
import time
from contextlib import AsyncExitStack

# Importe auch bei einem anderen Startverzeichnis ermöglichen.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from mcp import types
from mcp.client.session import ClientSession
from mcp.client.stdio import (StdioServerParameters,
                             get_default_environment, stdio_client)
from mcp.server import InitializationOptions, NotificationOptions
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from gateway.audit import AuditLog, AuditRecord
from gateway.config import GatewayConfig
from gateway import policy

# Nur diese zusätzlichen Umgebungsvariablen an die Server weitergeben.
WEITERGEREICHT = ("STUDY_SET", "GATEWAY_EGRESS_LOG")

log = logging.getLogger("gateway")


class SessionState:
    def __init__(self, session_id):
        self.session_id = session_id
        self.sensitive_accessed = False
        self.used_tools = []

    def record_access(self, tool_name, is_sensitive):
        self.used_tools.append(tool_name)
        # Sensiblen Zugriff bis zum Sitzungsende merken.
        if is_sensitive:
            self.sensitive_accessed = True


class UpstreamConnection:
    def __init__(self, server_config):
        self.config = server_config
        self.session = None
        self.tools = []

    async def connect(self, stack):
        command = self.config.command

        # Denselben Python-Interpreter wie für das Gateway verwenden.
        if command == "python" or command == "python3":
            command = sys.executable

        # SDK-Standardumgebung ergänzen, nicht die gesamte Host-Umgebung übernehmen.
        umgebung = dict(get_default_environment())
        for name in WEITERGEREICHT:
            if name in os.environ:
                umgebung[name] = os.environ[name]

        parameters = StdioServerParameters(
            command=command,
            args=self.config.args,
            cwd=PROJECT_ROOT,
            env=umgebung,
        )

        read, write = await stack.enter_async_context(stdio_client(parameters))
        self.session = await stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        await self.refresh_tools()

        log.info("Connected to '%s' (%d tools)", self.config.name, len(self.tools))

    async def refresh_tools(self):
        # Tool-Definitionen vom verbundenen Server laden.
        result = await self.session.list_tools()
        self.tools = list(result.tools)
        return self.tools


class Gateway:
    def __init__(self, config, audit=None):
        self.config = config
        if audit is None:
            audit = AuditLog()
        self.audit = audit

        self.upstreams = {}  # Servername -> Verbindung
        self.sessions = {}  # Sitzungskennung -> Zustand

        # Wird gesetzt, wenn alle Startversuche abgeschlossen sind.
        self.ready = asyncio.Event()

        self.server = Server(
            name="mcp-policy-gateway",
            title="MCP Policy Gateway",
            instructions="Aggregates internal and external MCP servers behind "
                         "a single endpoint.",
            version="0.1.0",
            on_list_tools=self.handle_list_tools,
            on_call_tool=self.handle_call_tool,
        )

    def get_session(self, session_id="default"):
        # Die stdio-Verbindung verwendet hier die gemeinsame Sitzung "default".
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionState(session_id)
        return self.sessions[session_id]

    async def connect_all(self, stack):
        # Server parallel starten, damit der Host nicht unnötig lange wartet.
        tasks = []
        for server_config in self.config.upstreams:
            tasks.append(self.connect_one(server_config, stack))

        await asyncio.gather(*tasks)
        self.ready.set()

    async def connect_one(self, server_config, stack):
        try:
            connection = UpstreamConnection(server_config)
            await connection.connect(stack)
            self.upstreams[server_config.name] = connection
        except Exception:
            # Die übrigen Server bleiben trotz dieses Startfehlers verfügbar.
            log.exception("Server '%s' could not be started", server_config.name)

    def visible_tools(self, session):
        # Erlaubte Tools sammeln und die ausgeblendeten Tools mitzählen.
        tools = []
        withheld = 0

        for server_name in self.upstreams:
            connection = self.upstreams[server_name]
            decision = policy.decide_visibility(self.config, session,
                                                server_name)

            if not decision.allowed:
                withheld = withheld + len(connection.tools)
                continue

            for tool in connection.tools:
                full_name = self.config.add_prefix(server_name, tool.name)
                # Nur den Namen ändern, alle anderen Tool-Felder übernehmen.
                renamed = tool.model_copy(update={"name": full_name})
                tools.append(renamed)

        return tools, withheld

    async def notify_tool_list_changed(self, context):
        try:
            # Den Host zum Aktualisieren auffordern; ob er das tut, entscheidet er selbst.
            await context.session.send_tool_list_changed()
        except Exception:
            # Der Aufruf soll weiterlaufen; die Aufrufprüfung bleibt aktiv.
            log.exception("Could not send tools/list_changed")

    async def handle_list_tools(self, context, params):
        start = time.perf_counter()

        try:
            # Beim ersten Abruf auf die Server warten, höchstens 20 Sekunden.
            await asyncio.wait_for(self.ready.wait(), timeout=20.0)
        except asyncio.TimeoutError:
            log.warning("Servers not ready yet, returning what is available")

        session = self.get_session()
        tools, withheld = self.visible_tools(session)

        # Ausgeblendete Tools als eigene Entscheidung im Audit festhalten.
        if withheld > 0:
            decision = "withheld"
            rule = policy.RULE_ID
            threat_id = policy.THREAT_ID
        else:
            decision = "forwarded"
            rule = None
            threat_id = None

        elapsed = (time.perf_counter() - start) * 1000
        self.audit.write(AuditRecord(
            event="list_tools",
            session_id=session.session_id,
            decision=decision,
            sensitive_flag=session.sensitive_accessed,
            rule=rule,
            threat_id=threat_id,
            latency_ms=elapsed,
            detail={"tool_count": len(tools), "withheld_count": withheld},
        ))

        return types.ListToolsResult(tools=tools)

    async def handle_call_tool(self, context, params):
        start = time.perf_counter()
        session = self.get_session()
        full_name = params.name
        arguments = params.arguments or {}

        try:
            # Aus dem Präfix den Zielserver bestimmen.
            server_name, tool_name = self.config.split_prefix(full_name)
        except ValueError as error:
            return self.error_result(session, full_name, str(error), start)

        if server_name not in self.upstreams:
            message = "unknown server: " + server_name
            return self.error_result(session, full_name, message, start)

        connection = self.upstreams[server_name]

        # Vor jeder Weiterleitung prüfen, auch bei bereits ausgeblendeten Tools.
        decision = policy.decide_invocation(self.config, session,
                                            server_name, tool_name)
        if not decision.allowed:
            return self.blocked_result(session, full_name, server_name,
                                       tool_name, decision, start)

        # Zustand vor dem nächsten await setzen, damit überlappende Aufrufe ihn sehen.
        became_restricted = policy.transition_on_call(
            self.config, session, server_name, tool_name)

        ankuendigen = became_restricted and policy.announce_transition(
            self.config)

        if ankuendigen:
            await self.notify_tool_list_changed(context)

        # Der Sitzungszustand ist vor der Weiterleitung bereits aktualisiert.
        result = await connection.session.call_tool(tool_name, arguments)

        if ankuendigen:
            # Hinweis direkt an das auslösende Ergebnis anhängen.
            result = self.append_notice(result)

        is_sensitive = self.config.is_sensitive(server_name, tool_name)

        elapsed = (time.perf_counter() - start) * 1000
        self.audit.write(AuditRecord(
            event="call_tool",
            session_id=session.session_id,
            decision="forwarded",
            upstream=server_name,
            tool=full_name,
            upstream_tool=tool_name,
            sensitive_flag=session.sensitive_accessed,
            latency_ms=elapsed,
            detail={"sensitive_source": is_sensitive,
                    "caused_transition": became_restricted},
        ))

        return result

    def append_notice(self, result):
        notice = policy.transition_notice(self.config)
        if len(notice.strip()) == 0:
            return result

        blocks = list(result.content)
        # Den letzten vorhandenen Textblock um den Hinweis ergänzen.
        for index in range(len(blocks) - 1, -1, -1):
            if blocks[index].type == "text":
                updated = blocks[index].model_copy(
                    update={"text": blocks[index].text + notice})
                blocks[index] = updated
                return result.model_copy(update={"content": blocks})

        # Ohne Textblock einen eigenen für den Hinweis anlegen.
        blocks.append(types.TextContent(type="text", text=notice.strip()))
        return result.model_copy(update={"content": blocks})

    # Ablehnung protokollieren, aber keine möglicherweise sensiblen Argumente speichern.
    def blocked_result(self, session, full_name, server_name, tool_name,
                       decision, start):
        elapsed = (time.perf_counter() - start) * 1000
        self.audit.write(AuditRecord(
            event="call_tool",
            session_id=session.session_id,
            decision="blocked",
            upstream=server_name,
            tool=full_name,
            upstream_tool=tool_name,
            sensitive_flag=session.sensitive_accessed,
            rule=decision.rule,
            threat_id=decision.threat_id,
            latency_ms=elapsed,
            detail={},
        ))

        return types.CallToolResult(
            content=[types.TextContent(type="text", text=decision.reason)],
            isError=True,
        )

    # Fehler protokollieren und als Tool-Ergebnis zurückgeben.
    def error_result(self, session, tool_name, message, start):
        elapsed = (time.perf_counter() - start) * 1000
        self.audit.write(AuditRecord(
            event="call_tool",
            session_id=session.session_id,
            decision="error",
            tool=tool_name,
            sensitive_flag=session.sensitive_accessed,
            latency_ms=elapsed,
            detail={"error": message},
        ))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            isError=True,
        )

    async def run(self):
        async with AsyncExitStack() as stack:
            options = InitializationOptions(
                server_name="mcp-policy-gateway",
                server_version="0.1.0",
                capabilities=self.server.get_capabilities(
                    notification_options=NotificationOptions(tools_changed=True),
                    experimental_capabilities={},
                ),
            )

            read, write = await stack.enter_async_context(stdio_server())

            # Server im Hintergrund verbinden, während der Gateway-Endpunkt schon läuft.
            background = asyncio.ensure_future(self.connect_all(stack))
            try:
                await self.server.run(read, write, options)
            finally:
                if not background.done():
                    background.cancel()


def setup_logging():
    # Für die Demo auch Diagnosemeldungen im jeweiligen Ergebnisordner sammeln.
    log_path = os.environ.get(
        "GATEWAY_LOG", os.path.join(PROJECT_ROOT, "logs", "gateway.log"))
    log_folder = os.path.dirname(os.path.abspath(log_path))
    if not os.path.exists(log_folder):
        os.makedirs(log_folder)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        handlers=[
            # stdout ist für MCP reserviert; Diagnosemeldungen gehen an stderr.
            logging.StreamHandler(sys.stderr),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )


async def main():
    setup_logging()
    log.info("Gateway starting, interpreter=%s", sys.executable)

    try:
        config = GatewayConfig.load()
    except Exception as error:
        # Bei ungültiger Konfiguration den konkreten Fehler melden und abbrechen.
        log.error("Configuration rejected: %s", error)
        raise

    try:
        gateway = Gateway(config)
        await gateway.run()
    except Exception as error:
        log.info("Gateway stopped (%s)", type(error).__name__)


if __name__ == "__main__":
    asyncio.run(main())

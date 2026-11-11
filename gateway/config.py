# Server, Zonen und sensible Tools aus der Konfiguration laden.

import json
import os


class UpstreamServer:
    def __init__(self, name, command, args=None, zone="internal",
                 sensitive_tools=None):
        self.name = name  # Präfix für die Tool-Namen
        self.command = command
        self.args = args or []
        self.zone = zone
        # Die Einstufung kommt aus der Konfiguration, nicht aus dem Tool-Ergebnis.
        self.sensitive_tools = sensitive_tools or []


class GatewayConfig:
    def __init__(self, upstreams, separator="__", enforcement=True,
                 notice_variant="standard"):
        self.upstreams = upstreams
        self.separator = separator
        # Wortlaut des Hinweises für den Variantenvergleich.
        self.notice_variant = notice_variant
        # Ohne Durchsetzung läuft die Baseline.
        self.enforcement = enforcement

    @staticmethod
    def load(path=None):
        # Ohne Pfadangabe die config.json neben dem Paket verwenden.
        if path is None:
            here = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(os.path.dirname(here), "config.json")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        upstreams = []
        for entry in data["upstreams"]:
            # Jede Zone muss ausdrücklich als intern oder extern angegeben sein.
            if "zone" not in entry:
                raise ValueError(
                    "upstream '" + str(entry.get("name", "?"))
                    + "' declares no zone; use \"internal\" or \"external\"")

            if entry["zone"] not in ("internal", "external"):
                raise ValueError(
                    "upstream '" + str(entry.get("name", "?"))
                    + "' declares zone '" + str(entry["zone"])
                    + "'; use \"internal\" or \"external\"")

            server = UpstreamServer(
                name=entry["name"],
                command=entry["command"],
                args=entry.get("args", []),
                zone=entry["zone"],
                sensitive_tools=entry.get("sensitive_tools", []),
            )
            upstreams.append(server)

        enforcement = data.get("enforcement", True)

        # Die Umgebung kann die Dateieinstellung mit on/off überschreiben.
        override = os.environ.get("GATEWAY_ENFORCEMENT")
        if override == "off":
            enforcement = False
        elif override == "on":
            enforcement = True

        # Bei einer unbekannten Hinweisvariante den Standard verwenden.
        variante = os.environ.get("GATEWAY_NOTICE", "standard").strip().lower()
        if variante not in ("standard", "nuechtern", "begruendet", "keine"):
            variante = "standard"

        return GatewayConfig(upstreams,
                             data.get("namespace_separator", "__"),
                             enforcement,
                             variante)

    def find_server(self, name):
        for server in self.upstreams:
            if server.name == name:
                return server
        return None

    def is_sensitive(self, server_name, tool_name):
        server = self.find_server(server_name)
        if server is None:
            return False
        return tool_name in server.sensitive_tools

    def add_prefix(self, server_name, tool_name):
        # Das Serverpräfix hält gleichnamige Tools auseinander.
        return server_name + self.separator + tool_name

    def split_prefix(self, full_name):
        if self.separator not in full_name:
            raise ValueError("tool name has no prefix: " + full_name)
        parts = full_name.split(self.separator, 1)
        return parts[0], parts[1]

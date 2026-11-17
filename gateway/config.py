import json
import os


class UpstreamServer:
    #Speichert die Konfiguration eines einzelnen MCP-Servers. "Upstream" bezeichnet den Server, an die der Tool-Aufruf weitergeleitet wird.
    def __init__(self, name, command, args=None, zone="internal",
                 sensitive_tools=None):
        self.name = name
        self.command = command
        self.args = args or []
        self.zone = zone
        self.sensitive_tools = sensitive_tools or []


class GatewayConfig:
    #Verwaltet die gesamten Einstellungen des Gateways
    def __init__(self, upstreams, separator="__", enforcement=True,
                 notice_variant="standard"):
        self.upstreams = upstreams
        self.separator = separator
        #Wortlaut des Hinweises für den Variantenvergleich
        self.notice_variant = notice_variant
        #Ohne Durchsetzung läuft die Baseline
        self.enforcement = enforcement

    #Die Methode ist statisch, da die Datei erst gelesen werden soll und erst danach ein Objekt erstellt wird
    @staticmethod
    def load(path=None):
        #Liest die die Konfigurationsdatei ein
        if path is None:
            here = os.path.dirname(os.path.abspath(__file__))
            #Ohne Pfadangabe wird config.jspn genutzt
            path = os.path.join(os.path.dirname(here), "config.json")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        upstreams = []
        for entry in data["upstreams"]:
            #Jede Zone muss als intern oder extern angegeben sein
            if "zone" not in entry:
                raise ValueError(
                    "upstream '" + str(entry.get("name", "?")) + "' declares no zone; use \"internal\" or \"external\"")
            if entry["zone"] not in ("internal", "external"):
                raise ValueError(
                    "upstream '" + str(entry.get("name", "?"))
                    + "' declares zone '" + str(entry["zone"])
                    + "'; use \"internal\" or \"external\"")
            #Zugehörigeres Server-Object wird erstellt
            server = UpstreamServer(
                name=entry["name"],
                command=entry["command"],
                args=entry.get("args", []),
                zone=entry["zone"],
                sensitive_tools=entry.get("sensitive_tools", []),
            )
            upstreams.append(server)

        enforcement = data.get("enforcement", True)

        #Eingefügt für die Demo-Variante, damit ein Startscript den Status der Durchsetzung überschreiben kann
        override = os.environ.get("GATEWAY_ENFORCEMENT")
        if override == "off":
            enforcement = False
        elif override == "on":
            enforcement = True

        #Bei einer falschen Hinweisvariante wird Standard verwendet
        variante = os.environ.get("GATEWAY_NOTICE", "standard").strip().lower()
        if variante not in ("standard", "nuechtern", "begruendet", "keine"):
            variante = "standard"

        return GatewayConfig(upstreams,
                             data.get("namespace_separator", "__"),
                             enforcement,
                             variante)

    def find_server(self, name):
        #Sucht einen Server anhand seines Namens
        for server in self.upstreams:
            if server.name == name:
                return server
        return None

    def is_sensitive(self, server_name, tool_name):
        #Prüft, ob das Tool in der Liste der sensiblen Tools dieses Server steht
        server = self.find_server(server_name)
        if server is None:
            return False
        return tool_name in server.sensitive_tools

    def add_prefix(self, server_name, tool_name):
        #Fügt Präfix in den Namen ein, um gleichnamige Tools auseinander zuhalten
        return server_name + self.separator + tool_name

    def split_prefix(self, full_name):
        #Entfernt das Präfix wieder in Servername und Tool-Name
        if self.separator not in full_name:
            raise ValueError("tool name has no prefix: " + full_name)
        parts = full_name.split(self.separator, 1)
        return parts[0], parts[1]

import json
import os
import threading
from datetime import datetime, timezone


def default_log_path():
    #Prüft zuerst, ob ein Dateipfad vorgegeben ist. Wenn keiner vorgegeben ist weren die json files in den ornder logs gespeichert.
    override = os.environ.get("GATEWAY_AUDIT_LOG")
    if override:
        return override
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "logs", "audit.jsonl")


class AuditRecord:
    #Sammelt alle Angaben zu einem Ereignis im Gateway
    def __init__(self, event, session_id, decision="forwarded",
                 upstream=None, tool=None, upstream_tool=None,
                 sensitive_flag=False, rule=None, threat_id=None,
                 latency_ms=None, detail=None):
        self.event = event
        self.session_id = session_id
        self.decision = decision
        self.upstream = upstream
        self.tool = tool  # Tool-Name mit Serverpräfix
        self.upstream_tool = upstream_tool  # Ursprünglicher Name beim Server
        self.sensitive_flag = sensitive_flag
        self.rule = rule
        self.threat_id = threat_id
        self.latency_ms = latency_ms
        self.detail = detail or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()  # Zeitangaben immer in UTC

    def to_dict(self):
        #Gibt alle gesammelten Angaben des AuditRecord zurück
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "session_id": self.session_id,
            "decision": self.decision,
            "upstream": self.upstream,
            "tool": self.tool,
            "upstream_tool": self.upstream_tool,
            "sensitive_flag": self.sensitive_flag,
            "rule": self.rule,
            "threat_id": self.threat_id,
            "latency_ms": self.latency_ms,
            "detail": self.detail,
        }


class AuditLog:
    #Verwaltet die Logdatei des Gateways
    def __init__(self, path=None):
        #Legt den Dateipfad fest und erstellt bei Bedarf den zugehörigen Ordner
        if path is None:
            path = default_log_path()
        self.path = path

        folder = os.path.dirname(self.path)
        if not os.path.exists(folder):
            os.makedirs(folder)

        self.lock = threading.Lock()

    def write(self, record):
        #Wandelt einen AuditRecord in json um und hängt ihn als neue Zeile an die Datei an
        line = json.dumps(record.to_dict(), ensure_ascii=False)
        with self.lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

    def read_all(self):
        #Liest die vorhandenen Einträge ein und gibt sie als Liste zurück
        if not os.path.exists(self.path):
            return []

        records = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(json.loads(line))
        return records

    def clear(self):
        #Wird gebraucht um Logdatein aus Testläufen zu löschen
        if os.path.exists(self.path):
            os.remove(self.path)

#Zwei echte MCP-Durchläufe mit lokalen Testservern und festen Testdaten.

import argparse
import asyncio
import hashlib
import json
import platform
import sys
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from gateway import policy


ROOT = Path(__file__).resolve().parent

CASES = {
    "1": ("C-2024-0917", "C-2024-1103", "MFH-88213-04", "structuring"),
    "2": ("C-2024-0658", "C-2024-1287", "CMS-70412-03", "layering"),
}

#Die Toolnamen so, wie das Gateway sie anbietet
INTERNAL = {"internal-docs__get_client_case", "internal-docs__search_client_records"}
EXTERNAL = {"external-research__submit_research_query", "external-research__search_case_law"}
ALL_TOOLS = INTERNAL | EXTERNAL


#---------------------------------------------------------------------------
#Hilfsfunktionen
#---------------------------------------------------------------------------

def save_json(path, value):
    #Schreibt ein Objekt als lesbare JSON-Datei
    text = json.dumps(value, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def read_records(path):
    #Liest eine JSONL-Datei (eine JSON-Zeile pro Eintrag) als Liste
    if not path.exists():
        return []

    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def result_text(result):
    #Holt den Text aus einer Tool-Antwort
    parts = []
    for block in result.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts)


def entries_with(records, key, value):
    #Gibt alle Einträge zurück, bei denen record[key] == value ist
    found = []
    for record in records:
        if record.get(key) == value:
            found.append(record)
    return found


async def wait_for_event(event, seconds):
    #Wartet höchstens Sekunden auf das Event und meldet, ob es eintrat
    try:
        await asyncio.wait_for(event.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass
    return event.is_set()


#---------------------------------------------------------------------------
#Zustand eines Durchlaufs
#---------------------------------------------------------------------------

class DemoRun:
    #Hält alles fest, was während einer Bedingung anfällt
    def __init__(self, mode, record_set, folder):
        self.mode = mode
        self.protected = (mode == "protected")
        self.record_set = record_set
        self.folder = folder

        first_case, second_case, marker, topic = CASES[record_set]
        self.first_case = first_case
        self.second_case = second_case
        self.marker = marker
        self.topic = topic

        self.checks = []          #Ergebnisse aller Prüfungen
        self.trace = []           #jeder Client-Schritt, landet in client-trace.json
        self.notifications = []   #Nachrichten, die das Gateway von sich aus schickt
        self.tools_changed = asyncio.Event()
        self.tools_before = set()
        self.tools_after = set()
        self.received_marker = False
        self.external_receipts = 0

    def check(self, name, passed):
        #Speichert eine Prüfung und gibt sie als OK oder FEHLER aus
        self.checks.append({"name": name, "passed": bool(passed)})
        if passed:
            print("  OK  " + name, flush=True)
        else:
            print("  FEHLER  " + name, flush=True)

    async def on_message(self, message):
        #Wird für jede Nachricht aufgerufen, die das Gateway unaufgefordert schickt
        method = getattr(message, "method", None)
        if method is None:
            return
        self.notifications.append(method)
        if method == "notifications/tools/list_changed":
            self.tools_changed.set()

    async def call(self, session, name, arguments):
        #Ruft ein Tool auf und schreibt den Schritt in client-trace.json
        result = await session.call_tool(name, arguments)
        # Dieser Testclient speichert nur die mitgelieferten synthetischen Testinhalte.
        self.trace.append({
            "tool": name,
            "arguments": arguments,
            "is_error": result.is_error,
            "result": result_text(result),
        })
        save_json(self.folder / "client-trace.json", self.trace)
        return result

    async def list_tools(self, session, stage):
        #Fragt die Toolliste ab und schreibt den Schritt in client-trace.json
        answer = await session.list_tools()
        names = set()
        for tool in answer.tools:
            names.add(tool.name)
        self.trace.append({"event": "tools/list", "stage": stage, "tools": sorted(names)})
        save_json(self.folder / "client-trace.json", self.trace)
        return names


#---------------------------------------------------------------------------
#Ein Durchlauf (baseline oder protected)
#---------------------------------------------------------------------------

def build_environment(run):
    #Umgebungsvariablen für das Gateway und die beiden Testserver.
    from mcp.client.stdio import get_default_environment

    #Keine vorhandenen Logpfade oder Baseline-Schalter aus der Umgebung übernehmen.
    environment = dict(get_default_environment())

    if run.protected:
        enforcement = "on"
    else:
        enforcement = "off"

    environment["PYTHONUTF8"] = "1"
    environment["STUDY_SET"] = run.record_set
    environment["GATEWAY_ENFORCEMENT"] = enforcement
    environment["GATEWAY_NOTICE"] = "standard"
    environment["GATEWAY_AUDIT_LOG"] = str(run.folder / "audit.jsonl")
    environment["GATEWAY_EGRESS_LOG"] = str(run.folder / "egress.jsonl")
    environment["GATEWAY_LOG"] = str(run.folder / "gateway.log")
    return environment


async def run_condition(mode, record_set, folder):
    #Startet das Gateway, führt die Aufruffolge aus und prüft die Logs
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    folder.mkdir()
    run = DemoRun(mode, record_set, folder)

    #Das Gateway läuft als eigener Prozess. Client und Gateway sprechen über dessen Standardein- und -ausgabe miteinander
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "run_gateway.py")],
        cwd=str(ROOT),
        env=build_environment(run),
    )

    #Fehlermeldungen des Gateways landen in stderr.log statt in der Ausgabe.
    with open(folder / "stderr.log", "w", encoding="utf-8") as stderr:
        async with stdio_client(parameters, errlog=stderr) as (read, write):
            #ClientSession legt das MCP-Protokoll über die beiden Kanäle
            async with ClientSession(read, write,
                                     message_handler=run.on_message,
                                     read_timeout_seconds=30) as session:
                await session.initialize()   # MCP-Handshake
                await run_steps(session, run)

    check_logs(run)
    return save_result(run)


async def run_steps(session, run):
    #Schritt 1: Zu Beginn muss das Gateway alle vier Tools anbieten
    run.tools_before = await run.list_tools(session, "before_sensitive_access")
    run.check("Zu Beginn sind alle vier Tools verfügbar", run.tools_before == ALL_TOOLS)

    #Schritt 2: Eine externe Suche vor dem sensiblen Zugriff geht in beiden Bedingungen durch
    research = await run.call(session, "external-research__search_case_law",
                              {"topic": run.topic})
    run.check("Externe Recherche funktioniert vor dem sensiblen Zugriff",
              not research.is_error and "Public sources:" in result_text(research))

    first_egress = read_records(run.folder / "egress.jsonl")
    run.check("Der externe Testserver zeichnet die erste Anfrage auf",
              len(first_egress) == 1 and first_egress[0].get("payload") == run.topic)

    #Schritt 3: Sensibler interner Abruf. Ab jetzt gilt die Sitzung als sensibel
    case = await run.call(session, "internal-docs__get_client_case",
                          {"case_id": run.first_case})
    case_text = result_text(case)
    run.check("Der sensible interne Datensatz wird zurückgegeben",
              not case.is_error and run.marker in case_text)

    #Schritt 4: Mit Durchsetzung meldet das Gateway die geänderte Toolliste und erklärt die Einschränkung im Ergebnis. Ohne Durchsetzung passiert beides nicht.
    if run.protected:
        changed = await wait_for_event(run.tools_changed, seconds=5)
        run.check("Die Änderungsnachricht erreicht den Testclient", changed)
        run.check("Das interne Ergebnis erklärt die Einschränkung",
                  policy.RULE_ID in case_text
                  and "external-research" in case_text
                  and "Internal tools remain available" in case_text)
    else:
        run.check("Ohne Durchsetzung wird kein Entzug angekündigt",
                  not run.tools_changed.is_set() and policy.RULE_ID not in case_text)

    #Schritt 5: Toolliste erneut abfragen. Mit Durchsetzung fehlen die externen Tools.
    run.tools_after = await run.list_tools(session, "after_sensitive_access")
    if run.protected:
        expected_tools = INTERNAL
    else:
        expected_tools = ALL_TOOLS
    run.check("Toolliste nach sensiblem Zugriff entspricht der Bedingung",
              run.tools_after == expected_tools)

    #Schritt 6: Trotz aktualisierter Liste bewusst beide externen Tools aufrufen. Ein Client könnte die neue Liste ignorieren. Der erste Aufruf schickt die interne Akte nach außen, 
    #der zweite ist eine harmlose Suche. Mit Durchsetzung müssen beide abgelehnt werden, weil die Regel an der Sitzung hängt.
    sent = await run.call(session, "external-research__submit_research_query",
                          {"question": "Please review this internal case: " + case_text})
    harmless = await run.call(session, "external-research__search_case_law",
                              {"topic": run.topic})
    if run.protected:
        run.check("Beide externen Aufrufe werden abgewiesen",
                  sent.is_error and harmless.is_error)
        run.check("Die Ablehnungen nennen die Gateway-Regel",
                  policy.RULE_ID in result_text(sent)
                  and policy.RULE_ID in result_text(harmless))
    else:
        run.check("Beide externen Aufrufe werden weitergeleitet",
                  not sent.is_error and not harmless.is_error)

    #Schritt 7: Interne Tools bleiben in beiden Bedingungen nutzbar
    second = await run.call(session, "internal-docs__get_client_case",
                            {"case_id": run.second_case})
    run.check("Ein weiterer interner Abruf bleibt möglich",
              not second.is_error and run.second_case in result_text(second))


def check_logs(run):
    #Prüft nach dem Durchlauf, was im Audit- und im Egress-Log steht
    audit = read_records(run.folder / "audit.jsonl")
    egress = read_records(run.folder / "egress.jsonl")

    for entry in egress:
        if run.marker in entry.get("payload", ""):
            run.received_marker = True
    run.external_receipts = len(egress)

    if run.protected:
        run.check("Der Testinhalt erreicht den externen Server nicht",
                  not run.received_marker)
        expected_receipts = 1   #nur die Suche aus Schritt 2
    else:
        run.check("Der Testinhalt erreicht den externen Server", run.received_marker)
        expected_receipts = 3   #Suche aus Schritt 2 und beide Aufrufe aus Schritt 6
    run.check("Die Zahl externer Empfangsbelege entspricht den weitergeleiteten Aufrufen",
              run.external_receipts == expected_receipts)

    #Audit-Log: fünf Toolaufrufe und zwei Abfragen der Toolliste.
    tool_calls = entries_with(audit, "event", "call_tool")
    tool_lists = entries_with(audit, "event", "list_tools")
    run.check("Alle fünf Aufrufe und beide Toollisten stehen im Audit",
              len(tool_calls) == 5 and len(tool_lists) == 2)

    #Das Audit soll Entscheidungen festhalten, aber keine Inhalte.
    audit_has_arguments = False
    for entry in audit:
        if "arguments" in entry:
            audit_has_arguments = True
    run.check("Das Gateway-Audit enthält keine Aufrufargumente oder Kontoreferenz",
              run.marker not in json.dumps(audit) and not audit_has_arguments)

    if run.protected:
        #Erwartet: zwei abgelehnte Aufrufe aus Schritt 6 und eine Toolliste, in der zwei externe Tools ausgeblendet wurden (Schritt 5).
        blocked = entries_with(audit, "decision", "blocked")
        withheld = entries_with(audit, "decision", "withheld")

        all_linked = True
        for entry in blocked + withheld:
            if entry.get("rule") != policy.RULE_ID:
                all_linked = False
            if entry.get("threat_id") != policy.THREAT_ID:
                all_linked = False
            if entry.get("sensitive_flag") is not True:
                all_linked = False

        two_tools_withheld = (len(withheld) == 1
                              and withheld[0].get("detail", {}).get("withheld_count") == 2)

        run.check("Ablehnungen und ausgeblendete Tools sind mit Regel und Bedrohung verknüpft",
                  len(blocked) == 2 and len(withheld) == 1
                  and all_linked and two_tools_withheld)
    else:
        only_forwarded = len(audit) > 0
        for entry in audit:
            if entry.get("decision") != "forwarded":
                only_forwarded = False
        run.check("Die Baseline protokolliert ausschließlich Weiterleitungen", only_forwarded)


def save_result(run):
    """Fasst den Durchlauf zusammen und speichert ihn als result.json."""
    passed = True
    for check in run.checks:
        if not check["passed"]:
            passed = False

    result = {
        "mode": run.mode,
        "passed": passed,
        "checks": run.checks,
        "notifications": run.notifications,
        "tools_before": sorted(run.tools_before),
        "tools_after": sorted(run.tools_after),
        "known_payload_received": run.received_marker,
        "external_receipts": run.external_receipts,
    }
    save_json(run.folder / "result.json", result)
    return result


#---------------------------------------------------------------------------
#Gesamtablauf
#---------------------------------------------------------------------------

def fingerprint():
    """SHA-256 jeder relevanten Datei, damit der getestete Codestand belegbar ist."""
    paths = [ROOT / "config.json", ROOT / "run_gateway.py",
             ROOT / "run_demo.py", ROOT / "requirements.txt"]
    paths += list((ROOT / "gateway").glob("*.py"))
    paths += list((ROOT / "servers").glob("*.py"))

    hashes = {}
    for path in sorted(paths):
        name = path.relative_to(ROOT).as_posix()
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


async def run(args, output):
    """Führt die gewählten Bedingungen nacheinander aus und schreibt summary.json."""
    if args.mode == "both":
        modes = ["baseline", "protected"]
    else:
        modes = [args.mode]

    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mcp": metadata.version("mcp"),
        "record_set": args.record_set,
        "file_sha256": fingerprint(),
        "conditions": [],
    }

    for mode in modes:
        if mode == "baseline":
            print("\nOHNE DURCHSETZUNG", flush=True)
        else:
            print("\nMIT DURCHSETZUNG", flush=True)

        #Ein Durchlauf darf höchstens 120 Sekunden dauern. Bricht er ab, wird der Fehler gespeichert und die nächste Bedingung läuft trotzdem
        try:
            result = await asyncio.wait_for(
                run_condition(mode, args.record_set, output / mode), timeout=120)
        except Exception as error:
            result = {"mode": mode, "passed": False,
                      "error": type(error).__name__ + ": " + str(error)}
            print("  FEHLER: " + result["error"], flush=True)
            save_json(output / (mode + "-error.json"), result)

        report["conditions"].append(result)
        save_json(output / "summary.json", report)

    report["passed"] = True
    for condition in report["conditions"]:
        if not condition["passed"]:
            report["passed"] = False
    save_json(output / "summary.json", report)

    if report["passed"]:
        print("\nAlle Prüfungen bestanden.")
    else:
        print("\nMindestens eine Prüfung ist fehlgeschlagen.")
    print("Ergebnisse: " + str(output))
    print("Die Demo prüft feste Aufrufsequenzen. Sie verwendet kein Sprachmodell.")

    if report["passed"]:
        return 0
    return 1


def main():
    #Umlaute auch in der Windows-Konsole korrekt ausgeben
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Lokale Gateway-Demo ohne API-Schlüssel.")
    parser.add_argument("--mode", choices=("both", "baseline", "protected"), default="both")
    parser.add_argument("--record-set", choices=tuple(CASES), default="1")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()

    #Vor dem Start prüfen, ob die festgelegte MCP-Version installiert ist
    try:
        installed = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        print("Abhängigkeiten fehlen. Bitte zuerst: python -m pip install -r requirements.txt")
        return 2
    if installed != "2.0.0":
        print("Diese Fassung erwartet mcp==2.0.0, installiert ist " + installed + ".")
        print("Bitte die festgelegten Abhängigkeiten in einer eigenen virtuellen Umgebung installieren.")
        return 2

    #Jeder Start bekommt einen neuen Ordner, bestehende Ergebnisse bleiben erhalten
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output_dir.resolve() / (stamp + "-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, exist_ok=False)

    print("MCP Policy Gateway – technische Demo")
    print("Alle Server laufen lokal. Die Falldaten sind synthetisch.")
    try:
        return asyncio.run(run(args, output))
    except KeyboardInterrupt:
        print("\nDemo abgebrochen. Bisherige Ergebnisse: " + str(output))
        return 130


if __name__ == "__main__":
    sys.exit(main())

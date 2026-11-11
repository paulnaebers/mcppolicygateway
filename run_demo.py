# Zwei echte MCP-Durchläufe mit lokalen Testservern und festen Testdaten.

import argparse
import asyncio
import hashlib
import json
import platform
import sys
import uuid
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CASES = {
    "1": ("C-2024-0917", "C-2024-1103", "MFH-88213-04", "structuring"),
    "2": ("C-2024-0658", "C-2024-1287", "CMS-70412-03", "layering"),
}
INTERNAL = {"internal-docs__get_client_case", "internal-docs__search_client_records"}
EXTERNAL = {"external-research__submit_research_query", "external-research__search_case_law"}


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_records(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def result_text(result):
    return "\n".join(block.text for block in result.content if block.type == "text")


async def run_condition(mode, record_set, folder):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
    from gateway import policy

    protected = mode == "protected"
    first_case, second_case, marker, topic = CASES[record_set]
    folder.mkdir()
    notifications = []
    changed = asyncio.Event()
    checks = []
    trace = []

    def check(name, passed):
        checks.append({"name": name, "passed": bool(passed)})
        print(f"  {'OK' if passed else 'FEHLER'}  {name}", flush=True)

    async def notification(message):
        method = getattr(getattr(message, "root", message), "method", None)
        if method:
            notifications.append(method)
        if method == "notifications/tools/list_changed":
            changed.set()

    # Keine vorhandenen Logpfade oder Baseline-Schalter aus der Umgebung übernehmen.
    environment = dict(get_default_environment())
    environment.update({
        "PYTHONUTF8": "1",
        "STUDY_SET": record_set,
        "GATEWAY_ENFORCEMENT": "on" if protected else "off",
        "GATEWAY_NOTICE": "standard",
        "GATEWAY_AUDIT_LOG": str(folder / "audit.jsonl"),
        "GATEWAY_EGRESS_LOG": str(folder / "egress.jsonl"),
        "GATEWAY_LOG": str(folder / "gateway.log"),
    })
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "run_gateway.py")],
        cwd=str(ROOT),
        env=environment,
    )

    async def call(session, name, arguments):
        result = await session.call_tool(name, arguments)
        # Dieser Testclient speichert nur die mitgelieferten synthetischen Testinhalte.
        trace.append({"tool": name, "arguments": arguments,
                      "is_error": result.is_error, "result": result_text(result)})
        save_json(folder / "client-trace.json", trace)
        return result

    async def list_tools(session, stage):
        answer = await session.list_tools()
        names = {tool.name for tool in answer.tools}
        trace.append({"event": "tools/list", "stage": stage, "tools": sorted(names)})
        save_json(folder / "client-trace.json", trace)
        return names

    with (folder / "stderr.log").open("w", encoding="utf-8") as stderr:
        async with AsyncExitStack() as stack:
            read, write = await stack.enter_async_context(stdio_client(parameters, errlog=stderr))
            session = await stack.enter_async_context(ClientSession(
                read, write, message_handler=notification, read_timeout_seconds=30))
            await session.initialize()

            before = await list_tools(session, "before_sensitive_access")
            check("Zu Beginn sind alle vier Tools verfügbar", before == INTERNAL | EXTERNAL)

            research = await call(session, "external-research__search_case_law", {"topic": topic})
            check("Externe Recherche funktioniert vor dem sensiblen Zugriff",
                  not research.is_error and "Public sources:" in result_text(research))
            initial_egress = read_records(folder / "egress.jsonl")
            check("Der externe Testserver zeichnet die erste Anfrage auf",
                  len(initial_egress) == 1 and initial_egress[0].get("payload") == topic)

            case = await call(session, "internal-docs__get_client_case", {"case_id": first_case})
            text = result_text(case)
            check("Der sensible interne Datensatz wird zurückgegeben", not case.is_error and marker in text)

            if protected:
                try:
                    await asyncio.wait_for(changed.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                check("Die Änderungsnachricht erreicht den Testclient", changed.is_set())
                check("Das interne Ergebnis erklärt die Einschränkung",
                      policy.RULE_ID in text and "external-research" in text
                      and "Internal tools remain available" in text)
            else:
                check("Ohne Durchsetzung wird kein Entzug angekündigt",
                      not changed.is_set() and policy.RULE_ID not in text)

            after = await list_tools(session, "after_sensitive_access")
            expected = INTERNAL if protected else INTERNAL | EXTERNAL
            check("Toolliste nach sensiblem Zugriff entspricht der Bedingung", after == expected)

            # Trotz aktualisierter Liste bewusst beide externen Tools aufrufen.
            sent = await call(session, "external-research__submit_research_query",
                              {"question": "Please review this internal case: " + text})
            harmless = await call(session, "external-research__search_case_law", {"topic": topic})
            check("Beide externen Aufrufe werden abgewiesen" if protected else "Beide externen Aufrufe werden weitergeleitet",
                  sent.is_error == protected and harmless.is_error == protected)
            if protected:
                check("Die Ablehnungen nennen die Gateway-Regel",
                      all(policy.RULE_ID in result_text(r) for r in (sent, harmless)))

            continued = await call(session, "internal-docs__get_client_case", {"case_id": second_case})
            check("Ein weiterer interner Abruf bleibt möglich",
                  not continued.is_error and second_case in result_text(continued))

    audit = read_records(folder / "audit.jsonl")
    egress = read_records(folder / "egress.jsonl")
    reached = any(marker in entry.get("payload", "") for entry in egress)
    check("Der Testinhalt erreicht den externen Server nicht" if protected else "Der Testinhalt erreicht den externen Server",
          reached == (not protected))
    check("Die Zahl externer Empfangsbelege entspricht den weitergeleiteten Aufrufen",
          len(egress) == (1 if protected else 3))
    check("Alle fünf Aufrufe und beide Toollisten stehen im Audit",
          sum(e.get("event") == "call_tool" for e in audit) == 5
          and sum(e.get("event") == "list_tools" for e in audit) == 2)
    check("Das Gateway-Audit enthält keine Aufrufargumente oder Kontoreferenz",
          marker not in json.dumps(audit) and all("arguments" not in e for e in audit))

    if protected:
        blocked = [e for e in audit if e.get("decision") == "blocked"]
        withheld = [e for e in audit if e.get("decision") == "withheld"]
        check("Ablehnungen und ausgeblendete Tools sind mit Regel und Bedrohung verknüpft",
              len(blocked) == 2 and len(withheld) == 1
              and all(e.get("rule") == policy.RULE_ID and e.get("threat_id") == policy.THREAT_ID
                      and e.get("sensitive_flag") is True for e in blocked + withheld)
              and withheld[0].get("detail", {}).get("withheld_count") == 2)
    else:
        check("Die Baseline protokolliert ausschließlich Weiterleitungen",
              bool(audit) and all(e.get("decision") == "forwarded" for e in audit))

    result = {"mode": mode, "passed": all(c["passed"] for c in checks),
              "checks": checks, "notifications": notifications,
              "tools_before": sorted(before), "tools_after": sorted(after),
              "known_payload_received": reached, "external_receipts": len(egress)}
    save_json(folder / "result.json", result)
    return result


def fingerprint():
    paths = [ROOT / "config.json", ROOT / "run_gateway.py", ROOT / "run_demo.py", ROOT / "requirements.txt"]
    paths += list((ROOT / "gateway").glob("*.py")) + list((ROOT / "servers").glob("*.py"))
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


async def run(args, output):
    modes = ("baseline", "protected") if args.mode == "both" else (args.mode,)
    report = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "mcp": metadata.version("mcp"), "record_set": args.record_set,
        "file_sha256": fingerprint(), "conditions": [],
    }
    for mode in modes:
        print("\n" + ("OHNE DURCHSETZUNG" if mode == "baseline" else "MIT DURCHSETZUNG"), flush=True)
        try:
            result = await asyncio.wait_for(run_condition(mode, args.record_set, output / mode), timeout=120)
        except Exception as error:
            result = {"mode": mode, "passed": False,
                      "error": f"{type(error).__name__}: {error}"}
            print("  FEHLER: " + result["error"], flush=True)
            save_json(output / (mode + "-error.json"), result)
        report["conditions"].append(result)
        save_json(output / "summary.json", report)

    report["passed"] = all(item["passed"] for item in report["conditions"])
    save_json(output / "summary.json", report)
    print("\n" + ("Alle Prüfungen bestanden." if report["passed"] else "Mindestens eine Prüfung ist fehlgeschlagen."))
    print("Ergebnisse: " + str(output))
    print("Die Demo prüft feste Aufrufsequenzen. Sie verwendet kein Sprachmodell.")
    return 0 if report["passed"] else 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Lokale Gateway-Demo ohne API-Schlüssel.")
    parser.add_argument("--mode", choices=("both", "baseline", "protected"), default="both")
    parser.add_argument("--record-set", choices=tuple(CASES), default="1")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    try:
        installed = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        print("Abhängigkeiten fehlen. Bitte zuerst: python -m pip install -r requirements.txt")
        return 2
    if installed != "2.0.0":
        print(f"Diese Fassung erwartet mcp==2.0.0; installiert ist {installed}.")
        print("Bitte die festgelegten Abhängigkeiten in einer eigenen virtuellen Umgebung installieren.")
        return 2

    # Jeder Start bekommt einen neuen Ordner; bestehende Ergebnisse bleiben erhalten.
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

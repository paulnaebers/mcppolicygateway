# MCP Policy Gateway

Ausführbares Artefakt zur Masterarbeit "A Threat-Model-Driven MCP Policy Gateway for
Enterprise AI Systems". Die technische Demo zeigt, wie der Gateway die Weitergabe interner 
Testdaten an einen externen MCP-Dienst verhindert. Sie vergleicht denselben Gateway mit deaktivierter und
aktivierter Durchsetzung.

## Schnellstart

Voraussetzung ist Python 3.10. Die eigentliche
Demo verwendet anschließend ausschließlich lokale Prozesse.

Das Repository über **Code → Download ZIP** herunterladen und entpacken oder
mit Git beziehen:

```text
git clone https://github.com/paulnaebers/mcppolicygateway.git
cd mcppolicygateway
```

Das Terminal im entpackten Projektordner öffnen. Eine neue Python-Umgebung
anlegen und die festgelegten Abhängigkeiten installieren.

### Windows / PowerShell

```powershell
py -3.10 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run_demo.py
```

Falls der Befehl `py` fehlt, kann bei installiertem Python 3.10 stattdessen
`python -m venv .venv` verwendet werden. Eine Aktivierung der Umgebung ist
bei diesen Befehlen nicht nötig.

### Linux / macOS

```sh
python3.10 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python run_demo.py
```

## Was die Demo macht

Jede Bedingung startet einen eigenen Gateway-Prozess mit einer frischen Sitzung.
Der Ablauf verwendet echte MCP-Nachrichten über stdio.

1. Die Toolliste abrufen und eine harmlose externe Recherche durchführen.
2. Einen sensiblen internen Datensatz abrufen.
3. Die Toolliste erneut abrufen und die Änderungsnachricht prüfen.
4. Bewusst einen externen Aufruf mit dem internen Testinhalt versuchen.
5. Auch einen harmlosen Aufruf des zweiten externen Tools versuchen.
6. Einen weiteren internen Datensatz abrufen.
7. Die Antworten mit dem Gateway-Audit und dem Empfangsprotokoll des externen
   Testservers vergleichen.

| Beobachtung | Ohne Durchsetzung | Mit Durchsetzung |
| --- | --- | --- |
| Externe Recherche vor sensiblem Zugriff | Möglich | Möglich |
| Tools nach sensiblem Zugriff | Vier Tools | Zwei interne Tools |
| Änderungsnachricht und Erklärung des Entzugs | Kein Entzug | Vorhanden |
| Spätere externe Aufrufe | Weitergeleitet | Abgewiesen |
| Bekannte Kontoreferenz beim externen Server | Empfangen | Nicht empfangen |
| Weiterer interner Abruf | Möglich | Möglich |

Bei Erfolg endet das Programm mit **„Alle Prüfungen bestanden.“** und nennt
den Ergebnisordner. Eine fehlgeschlagene Prüfung führt zu einem Rückgabewert
ungleich null. Ohne Durchsetzung ist die erfolgreiche Übertragung des
Testinhalts das erwartete Ergebnis des Baseline-Tests.

## Ergebnisse nachlesen

Jeder Start erstellt einen eigenen Unterordner in `results/`. Bereits vorhandene
Ergebnisse werden nicht gelöscht. Pro Bedingung entstehen folgende Dateien:

| Datei | Inhalt |
| --- | --- |
| `result.json` | Einzelne Prüfungen, Toollisten und Gesamtergebnis der Bedingung |
| `audit.jsonl` | Gateway-Entscheidungen mit Sitzungszustand, Regel und Bedrohungskennung |
| `egress.jsonl` | Vom externen Testserver tatsächlich empfangene Argumente |
| `client-trace.json` | Vom Testclient gesendete Aufrufe und erhaltene Antworten |
| `gateway.log`, `stderr.log` | Diagnosemeldungen für die Fehlersuche |

Die gemeinsame Datei `summary.json` nennt beide Ergebnisse, Python- und
SDK-Version sowie Prüfsummen der relevanten Dateien. Das Gateway-Audit enthält
keine Aufrufargumente. Der separate Testclient und der externe Testserver halten
die Testinhalte fest, damit die konkrete Übertragung überprüft werden
kann. Eine verweigerte Anfrage allein wäre dafür kein ausreichender Beleg.

## Aufbau und Bezug zur Arbeit

| Datei / Ordner | Aufgabe |
| --- | --- |
| `gateway/policy.py` | Regel für Discovery und Aufrufe sowie Erläuterungstexte |
| `gateway/proxy.py` | MCP-Verbindungen, Sitzungszustand, Durchsetzung und Audit |
| `gateway/config.py` | Zonen, sensitive Tools und Konfigurationsprüfung |
| `gateway/audit.py` | Format und Speicherung der Audit-Einträge |
| `config.json` | Zwei Testserver mit expliziten Zonen und sensiblen Tools |
| `servers/` | Lokale interne und externe MCP-Testserver |
| `run_demo.py` | Deterministischer Testclient und Ergebnisprüfung |
| `run_gateway.py` | Einstiegspunkt für einen MCP-Host |
| `requirements.txt` | Festgelegte direkte und indirekte Paketversionen |

`run_gateway.py` allein startet keine Oberfläche. Der Prozess wartet auf
MCP-Anfragen über seine Standardeingabe. `run_demo.py` startet diesen Prozess
und übernimmt die Client-Rolle.

## Prüfung und Fehlersuche

Der Aufbau wurde lokal unter Windows mit Python 3.10 in einer neu angelegten
virtuellen Umgebung geprüft. Zusätzlich liefen Installation, Demo und Tests
unter Linux mit Python 3.13 und 3.14. Python 3.15 wird von den festgelegten
Abhängigkeiten derzeit nicht unterstützt, die Installation bricht dort ab.

### Andere Python-Version verwenden

Die Python-Version wird beim Anlegen der virtuellen Umgebung festgelegt. Ein
systemweites Umschalten ist nicht nötig.

Ist die gewünschte Version bereits installiert, wählt der Launcher `py` sie
unter Windows aus. `py -0` zeigt alle installierten Versionen an.

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe run_demo.py
```

Ist die Version nicht installiert, lädt `uv` sie automatisch herunter, ohne die
vorhandene Python-Installation zu verändern. `uv` wird einmalig mit
`pip install uv` installiert.

```powershell
uv venv --python 3.14
uv pip install -r requirements.txt
.venv\Scripts\python.exe run_demo.py
```

Unter Linux und macOS lautet der letzte Befehl `.venv/bin/python run_demo.py`.

Eine vorhandene Umgebung mit einer anderen Version vorher löschen, also den
Ordner `.venv` entfernen.

Bei fehlenden Paketen die Installation mit dem Python aus `.venv` wiederholen.
Bei einer fehlgeschlagenen Demo zuerst `summary.json` und die `stderr.log` der
betroffenen Bedingung lesen. Die Demo benötigt keine eingehenden öffentlichen
Netzwerkverbindungen.

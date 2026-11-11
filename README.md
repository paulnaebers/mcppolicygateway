# MCP Policy Gateway

Ausführbares Artefakt zur Masterarbeit "A Threat-Model-Driven MCP Policy Gateway for
Enterprise AI Systems". Die technische Demo zeigt, wie der Gateway die Weitergabe interner 
Testdaten an einen externen MCP-Dienst verhindert. Sie vergleicht denselben Gateway mit deaktivierter und
aktivierter Durchsetzung.

**Es werden kein API-Schlüssel, kein Sprachmodell und kein Claude Desktop benötigt.**
Der Testclient, der Gateway und beide MCP-Testserver laufen auf demselben Rechner.
Der als „extern“ konfigurierte Server bildet die externe Vertrauenszone nach.
Alle Mandanten- und Kontodaten sind synthetische Testdaten. Der Recherche-Server
liefert fest hinterlegte Beispiele, keine Live-Recherche.

## Schnellstart

Voraussetzung ist Python 3.10. Internetzugriff wird zum Herunterladen des
Repositories und zur ersten Installation der Pakete benötigt. Die eigentliche
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

Die Regel schränkt die Sitzung bereits **vor der Weiterleitung** des sensiblen
Aufrufs ein. Auch ein späterer Fehler dieses Aufrufs setzt den Zustand nicht
zurück. Die Regel bewertet die konfigurierte Sensitivität und die Zielzone.
Sie untersucht weder ausgehende Argumente noch die Absicht eines Nutzers.

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
die synthetischen Inhalte fest, damit die konkrete Übertragung überprüft werden
kann. Eine verweigerte Anfrage allein wäre dafür kein ausreichender Beleg.

`results/`, `logs/` und lokale Python-Umgebungen werden nicht versioniert.
Das Repository enthält keine Teilnehmeraufzeichnungen oder historischen
Studienlogs. Neue Demo-Ergebnisse ersetzen die Belege in der Arbeit nicht.

## Weitere Aufrufe

Die folgenden Beispiele verwenden die Windows-Umgebung. Unter Linux/macOS
`.venv/bin/python` anstelle von `.venv\Scripts\python.exe` verwenden.

```powershell
# Nur die geschützte Bedingung ausführen
.venv\Scripts\python.exe run_demo.py --mode protected

# Beide Bedingungen mit dem zweiten synthetischen Datensatz prüfen
.venv\Scripts\python.exe run_demo.py --record-set 2

# Einen anderen Ordner für neue Ergebnisse wählen
.venv\Scripts\python.exe run_demo.py --output-dir "C:\Temp\Gateway-Ergebnisse"

# Zusätzliche Tests der Konfiguration und Zustandsregel
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`--mode baseline` führt nur den ungeschützten Lauf aus. Die Demo setzt
Durchsetzung, Hinweisvariante, Datensatz und Logpfade für ihre eigenen Prozesse
ausdrücklich. Bereits gesetzte Gateway-Umgebungsvariablen verändern diese
Vergleichsbedingungen nicht.

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

Die ursprüngliche Kennung **D-I-01** bleibt im Quellcode und im Audit erhalten.
Sie entspricht **C-I-01** im aktuellen Bedrohungskatalog der Arbeit. Die
Gateway-Regel und ihre Prüfung bei Discovery und Invocation entsprechen dem
vorhandenen Prototyp. Die Kommentare wurden gekürzt und auf Deutsch formuliert.
Für das Abgabepaket wurden ein eigenständiger Demo-Client, Installationsangaben
und ein konfigurierbarer Pfad für Diagnosemeldungen ergänzt.

## Aussagekraft und Grenzen

Die Demo prüft die Gateway-Kontrollen an fest vorgegebenen Aufrufsequenzen.
Der Testclient stellt die sensible externe Anfrage bewusst her. Das ist kein
Nachweis darüber, wie häufig ein Sprachmodell solche Anfragen erzeugt, und
keine Wiederholung der Nutzerstudie. Die Studien-Web-App ist nicht enthalten.

Discovery und Invocation werden getrennt beobachtet. Der Demo-Client fragt
die Toolliste nach dem Zugriff ausdrücklich erneut ab. Daraus folgt nicht,
dass jeder Host eine Änderungsnachricht automatisch verarbeitet oder frühere
Toolbeschreibungen aus dem Modellkontext entfernt. Der Start einer neuen Sitzung
mit weiterverwendetem Modellkontext sowie sämtliche möglichen Reihenfolgen
gleichzeitiger Aufrufe werden hier nicht überprüft.

Die Regel sperrt nach sensiblem Zugriff auch harmlose externe Recherche.
Die Demo zeigt diese Einschränkung, misst aber nicht ihren Usability-Aufwand.
Provider-Anfragen und Credential-Speicherung bleiben außerhalb dieses Testpfads.

## Prüfung und Fehlersuche

Der Aufbau wurde lokal unter Windows mit Python 3.10 in einer neu angelegten
virtuellen Umgebung geprüft. Der Workflow
[Technical demo](https://github.com/paulnaebers/mcppolicygateway/actions/workflows/demo.yml)
prüft Installation, zusätzliche Tests und beide Datensätze auch auf GitHub.
Die Ergebnisse des jeweiligen Commits sind dort einsehbar.

Bei fehlenden Paketen die Installation mit dem Python aus `.venv` wiederholen.
Bei einer fehlgeschlagenen Demo zuerst `summary.json` und die `stderr.log` der
betroffenen Bedingung lesen. Die Demo benötigt keine eingehenden öffentlichen
Netzwerkverbindungen. Python und das MCP SDK verwenden jedoch lokale
Kommunikation und Kindprozesse, die eine restriktive Laufzeitumgebung zulassen
muss.

Für die Abgabe einen festen Commit oder Versions-Tag referenzieren. Damit bleibt
nachvollziehbar, welcher Stand ausgeführt wurde.

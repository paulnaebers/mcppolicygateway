RULE_ID = "external-withdrawal-after-sensitive-access"
#Kennung des Hauptszenarios
THREAT_ID = "C-I-01" 

class Decision:
    #Speichert das Ergebnis einer Regelprüfung
    def __init__(self, allowed, rule=None, threat_id=None, reason=None):
        self.allowed = allowed
        self.rule = rule
        self.threat_id = threat_id
        self.reason = reason


def is_external(config, server_name):
    #Prüft, ob ein server als extern konfiguriert ist
    server = config.find_server(server_name)
    #Unbekannte Server vorsichtshalber als extern behandeln.
    if server is None:
        return True
    return server.zone == "external"


def restricts_external(session):
    #Prüft, ob die Sitzung bereits auf eine sensible Quelle zugegriffen hat
    return session.sensitive_accessed


def decide_visibility(config, session, server_name):
    #Entscheidet, ob die Tools eines Server angezeigt werden dürfen
    if not config.enforcement:
        return Decision(True)
    if not restricts_external(session):
        return Decision(True)
    if not is_external(config, server_name):
        return Decision(True)

    return Decision(
        False,
        rule=RULE_ID,
        threat_id=THREAT_ID,
        reason="external capabilities are withheld after sensitive access",
    )


def decide_invocation(config, session, server_name, tool_name):
    #Prüft einen tatsächlichen Tool-Aufruf mit derselben Regel
    decision = decide_visibility(config, session, server_name)
    if decision.allowed:
        return decision

    #Bei einer Ablehnung wird eine Erklärung ergänzt, welches Tool gesperrt ist.
    reason = (
        "'" + config.add_prefix(server_name, tool_name) + "' is not available "
        "in this session. External tools were withdrawn because this session "
        "accessed a sensitive internal source. Internal tools remain "
        "available. Rule: " + RULE_ID
    )
    return Decision(False, rule=RULE_ID, threat_id=THREAT_ID, reason=reason)


def announce_transition(config):
    #Gibt zurück, ob die Durchsetzung aktiviert ist. Damit wird gesteuert, ob der Gateway den Entzug externer Tools ankündigen soll.
    return config.enforcement


def transition_notice(config):
    #Ertsellt den Hinweistext
    external = []
    for server in config.upstreams:
        if server.zone == "external":
            external.append(server.name)
    namen = ", ".join(sorted(external))

    variante = getattr(config, "notice_variant", "standard")

    #Vergleichslauf ohne Hinweis
    if variante == "keine":
        return ""
    #Kurze Variante ohne Regelname
    if variante == "nuechtern":
        return (
            "\n\nThis record comes from a confidential internal source. For "
            "the rest of this session, tools from " + namen + " are no longer "
            "available. Internal tools are unaffected."
        )
    #Begründete Variante
    if variante == "begruendet":
        return (
            "\n\nThis record came from an internal source. Anything sent to "
            "an external service leaves the organisation, and this gateway "
            "cannot tell in advance which part of a record a query will "
            "carry, so tools from " + namen + " are withdrawn for the rest "
            "of this session as a precaution. Internal tools are unaffected."
        )

    return (
        "\n\n[gateway] External capabilities have been withdrawn for the "
        "remainder of this session because this result comes from a sensitive "
        "internal source. Affected servers: " + namen
        + ". Internal tools remain available. Rule: " + RULE_ID
    )


def transition_on_call(config, session, server_name, tool_name):
    #Prüft die Sensitivitätsklassifikation des Tools und erfasst den Zugriff in der Sitzung.
    full_name = config.add_prefix(server_name, tool_name)
    is_sensitive = config.is_sensitive(server_name, tool_name)

    #Vor der Weiterleitung aktualisieren; bei einem Fehler nicht zurücksetzen.
    was_restricted = restricts_external(session)
    session.record_access(full_name, is_sensitive)

    #Nur der erste Wechsel soll die Benachrichtigung auslösen.
    return restricts_external(session) and not was_restricted

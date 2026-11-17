import json
import tempfile
import unittest
from pathlib import Path

from gateway.config import GatewayConfig, UpstreamServer
from gateway.policy import decide_invocation, decide_visibility, transition_on_call
from gateway.proxy import SessionState


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.config = GatewayConfig([
            UpstreamServer("internal", "python", zone="internal", sensitive_tools=["secret"]),
            UpstreamServer("external", "python", zone="external"),
        ])
        self.session = SessionState("test")

    def test_external_access_changes_only_after_sensitive_call(self):
        self.assertTrue(decide_invocation(self.config, self.session, "external", "search").allowed)
        self.assertFalse(transition_on_call(self.config, self.session, "internal", "public"))
        self.assertTrue(decide_visibility(self.config, self.session, "external").allowed)
        self.assertTrue(transition_on_call(self.config, self.session, "internal", "secret"))
        self.assertFalse(decide_visibility(self.config, self.session, "external").allowed)
        self.assertFalse(decide_invocation(self.config, self.session, "external", "search").allowed)
        self.assertTrue(decide_invocation(self.config, self.session, "internal", "public").allowed)

    def test_later_public_access_does_not_clear_sensitive_state(self):
        transition_on_call(self.config, self.session, "internal", "secret")
        self.assertFalse(transition_on_call(self.config, self.session, "internal", "public"))
        self.assertTrue(self.session.sensitive_accessed)
        self.assertFalse(decide_invocation(self.config, self.session, "external", "search").allowed)

    def test_baseline_tracks_state_without_blocking(self):
        self.config.enforcement = False
        transition_on_call(self.config, self.session, "internal", "secret")
        self.assertTrue(self.session.sensitive_accessed)
        self.assertTrue(decide_visibility(self.config, self.session, "external").allowed)
        self.assertTrue(decide_invocation(self.config, self.session, "external", "search").allowed)

    def test_policy_treats_unknown_server_as_external_after_transition(self):
        transition_on_call(self.config, self.session, "internal", "secret")
        self.assertFalse(decide_visibility(self.config, self.session, "unknown").allowed)
        self.assertFalse(decide_invocation(self.config, self.session, "unknown", "tool").allowed)

    def test_fresh_session_has_independent_state(self):
        transition_on_call(self.config, self.session, "internal", "secret")
        fresh = SessionState("fresh")
        self.assertFalse(fresh.sensitive_accessed)
        self.assertTrue(decide_invocation(self.config, fresh, "external", "search").allowed)
        self.assertFalse(decide_invocation(self.config, self.session, "external", "search").allowed)

    def test_missing_or_invalid_zone_is_rejected(self):
        for zone in (None, "extern", ""):
            with self.subTest(zone=zone), tempfile.TemporaryDirectory() as directory:
                entry = {"name": "server", "command": "python"}
                if zone is not None:
                    entry["zone"] = zone
                path = Path(directory) / "config.json"
                path.write_text(json.dumps({"upstreams": [entry]}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    GatewayConfig.load(str(path))


if __name__ == "__main__":
    unittest.main()

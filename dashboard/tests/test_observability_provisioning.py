import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_ROOT = REPO_ROOT / "dashboard"


def test_grafana_provisions_dashboard_with_required_panels_and_metrics():
    provisioning_dir = DASHBOARD_ROOT / "grafana" / "provisioning"
    provider_dir = provisioning_dir / "dashboards"
    provider = (provider_dir / "dashboards.yml").read_text(encoding="utf-8")
    datasource_config = (
        provisioning_dir / "datasources" / "datasources.yml"
    ).read_text(encoding="utf-8")
    dashboard = json.loads(
        (provider_dir / "saiv-observability.json").read_text(encoding="utf-8")
    )

    dashboard_path = "/etc/grafana/provisioning/dashboards"
    assert f"path: {dashboard_path}" in provider
    assert "uid: saiv-prometheus" in datasource_config
    assert dashboard["uid"] == "saiv-observability"

    panels = {panel["title"]: panel for panel in dashboard["panels"]}
    expected_queries = {
        "HTTP Request Rate": "sum(rate(http_requests_total[5m]))",
        "p95 Request Latency": "histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m]))) * 1000",
        "HTTP 5xx Error Rate": "http_requests_total{status=~\"5..\"}",
        "Check-in Decisions by Decision": "sum by (decision) (rate(checkin_decisions_total[5m]))",
    }
    for title, query_fragment in expected_queries.items():
        panel = panels[title]
        target = panel["targets"][0]
        assert query_fragment in target["expr"]
        assert target["datasource"]["uid"] == "saiv-prometheus"


def test_prometheus_loads_compose_mounted_rules_with_required_alerts():
    prometheus_config = (DASHBOARD_ROOT / "prometheus.yml").read_text(
        encoding="utf-8"
    )
    alert_rules = (DASHBOARD_ROOT / "prometheus-alert-rules.yml").read_text(
        encoding="utf-8"
    )
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "rule_files:" in prometheus_config
    assert "- /etc/prometheus/alert_rules.yml" in prometheus_config
    assert (
        "./dashboard/prometheus-alert-rules.yml:/etc/prometheus/alert_rules.yml:ro"
        in compose
    )

    assert "alert: HighFlaggedCheckinShare" in alert_rules
    assert 'checkin_decisions_total{decision="flagged"}[15m]' in alert_rules
    assert "clamp_min(sum(increase(checkin_decisions_total[15m])), 1)" in alert_rules
    assert "> 0.30" in alert_rules

    assert "alert: ExcessiveFailedLogins" in alert_rules
    assert 'method="POST"' in alert_rules
    assert 'endpoint="/api/v1/auth/login"' in alert_rules
    assert 'status="401"' in alert_rules
    assert "[5m]" in alert_rules
    assert "> 20" in alert_rules
    assert "severity: warning" in alert_rules
    assert "summary:" in alert_rules
    assert "description:" in alert_rules

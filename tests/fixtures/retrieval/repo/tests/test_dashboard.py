"""Dashboard 测试：渲染 metrics。"""

from web.dashboard import render_dashboard


def test_render_dashboard_includes_metrics() -> None:
    rendered = render_dashboard([{"name": "requests", "value": 3}])
    assert "dashboard metrics: 1" == rendered

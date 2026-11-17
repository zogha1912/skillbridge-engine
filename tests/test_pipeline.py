import asyncio

import etl.pipeline as pipeline


def test_select_steps_keeps_pipeline_order():
    assert pipeline.select_steps(None, None) == ["esco", "onet", "crosswalk", "embed"]
    assert pipeline.select_steps(["embed", "esco"], None) == ["esco", "embed"]
    assert pipeline.select_steps(None, ["esco", "embed"]) == ["onet", "crosswalk"]


def fake_steps(results: dict[str, int], calls: list[str]):
    def builder(scope):
        def make(name):
            async def step(argv):
                calls.append(name)
                return results.get(name, 0)

            return step

        return {name: (make(name), []) for name in pipeline.STEP_ORDER}

    return builder


def test_run_stops_at_first_failure(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "build_steps", fake_steps({"onet": 1}, calls))
    assert asyncio.run(pipeline.run(list(pipeline.STEP_ORDER), "ict")) == 1
    assert calls == ["esco", "onet"]


def test_run_reports_quota_stop_from_embed(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "build_steps", fake_steps({"embed": 2}, calls))
    assert asyncio.run(pipeline.run(["embed"], "ict")) == pipeline.QUOTA_EXIT


def test_run_all_ok(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "build_steps", fake_steps({}, calls))
    assert asyncio.run(pipeline.run(list(pipeline.STEP_ORDER), "ict")) == 0
    assert calls == list(pipeline.STEP_ORDER)

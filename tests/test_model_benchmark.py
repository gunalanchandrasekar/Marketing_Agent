from benchmark_models import write_results


def test_benchmark_partial_results_do_not_become_recommendation(tmp_path):
    output = tmp_path / "benchmark.json"
    rows = [{"model": "qwen3:30b", "quality_points": 7, "elapsed_seconds": 20.0, "errors": []}]
    partial = write_results(output, rows, complete=False)
    assert output.exists()
    assert partial["recommended_model"] is None
    assert partial["complete"] is False


def test_benchmark_recommends_fastest_among_equally_accurate(tmp_path):
    rows = [
        {"model": "slower", "quality_points": 7, "elapsed_seconds": 40, "errors": []},
        {"model": "faster", "quality_points": 7, "elapsed_seconds": 18, "errors": []},
        {"model": "inaccurate", "quality_points": 5, "elapsed_seconds": 1, "errors": []},
    ]
    result = write_results(tmp_path / "benchmark.json", rows, complete=True)
    assert result["recommended_model"] == "faster"
    assert result["complete"] is True

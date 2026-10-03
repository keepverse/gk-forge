"""The guard tests were structural and the predicate probe imported schema directly, so neither
executed the runner's call site - and the suite caught a NameError in it 58 times. This binds the
name the module actually uses at the call site, which is the check that was missing.
"""
import importlib


def test_the_runner_binds_the_predicate_it_calls():
    runner = importlib.import_module("seedsmith.adapters.creatures.run.runner")
    assert hasattr(runner, "seed_consumer_violations"), (
        "runner calls seed_consumer_violations but does not bind it - the guard would raise "
        "NameError on the first species instead of refusing it")
    src = importlib.import_module("seedsmith.adapters.creatures.run.runner").__file__
    text = open(src, encoding="utf-8").read()
    assert "seed_consumer_violations(" in text, "the runner should still call it"

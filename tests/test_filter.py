from aprs_stats.stats import Filter


def test_filter_all_devices():
    where, params = Filter(calls=None).where()
    assert where == "true"
    assert params == {}


def test_filter_no_devices():
    # "keine" gewählt: leere Liste darf nicht als "alle" gelten
    where, params = Filter(calls=[]).where()
    assert "ANY(%(calls)s)" in where
    assert params["calls"] == []


def test_filter_some_devices():
    where, params = Filter(calls=["HB3XVA-9"]).where("received_at")
    assert where == "true AND callsign = ANY(%(calls)s)"
    assert params == {"calls": ["HB3XVA-9"]}

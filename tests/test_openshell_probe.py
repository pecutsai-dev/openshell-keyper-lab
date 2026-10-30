from approval_lab.openshell_probe import inspect_sources


def test_unrelated_mentions_do_not_verify_update_config_contract():
    checks = inspect_sources({
        "proto/openshell.proto": 'message Other { map<string, string> annotations = 1; }',
        "proto/gateway_interceptor.proto": '',
        "crates/openshell-gateway-interceptors/src/routes.rs": '// "UpdateConfig"',
    })
    assert not checks["update_config_allowlisted"]
    assert not checks["update_config_request"]
    assert not checks["approval_reference_carrier"]
    assert not checks["optimistic_concurrency"]


def test_missing_concurrency_cannot_be_reported_as_verified():
    checks = inspect_sources({
        "proto/openshell.proto": 'message UpdateConfigRequest {\n map<string, string> annotations = 9;\n}',
        "proto/gateway_interceptor.proto": '',
        "crates/openshell-gateway-interceptors/src/routes.rs": 'const INTERCEPTABLE_METHODS: &[&str] = &["UpdateConfig"];',
    })
    assert checks["approval_reference_carrier"]
    assert checks["update_config_allowlisted"]
    assert not checks["optimistic_concurrency"]

"""ONE shared sounddevice stub for the whole suite.

Every test module that touches audio imports this FIRST. The lesson it
encodes: per-file partial stubs break under combined discovery, because
whichever test file runs first wins sys.modules -- so the stub must be
complete and shared.
"""
import sys
import types


def install():
    existing = sys.modules.get("sounddevice")
    if existing is not None and getattr(existing, "_is_test_stub", False):
        return existing
    dummy_stream = lambda **k: types.SimpleNamespace(  # noqa: E731
        active=True, start=lambda: None, close=lambda: None,
        abort=lambda: None)
    stub = types.SimpleNamespace(
        _is_test_stub=True,
        PortAudioError=Exception,
        query_devices=lambda *a, **k: [],
        check_input_settings=lambda **k: None,
        check_output_settings=lambda **k: None,
        _terminate=lambda: None,
        _initialize=lambda: None,
        InputStream=dummy_stream,
        OutputStream=dummy_stream,
    )
    sys.modules["sounddevice"] = stub
    return stub

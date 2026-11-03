from retropi.network import Wifi


def fake_nmcli(output):
    calls = []

    def run(*args):
        calls.append(args)
        return output

    return run, calls


def test_connected():
    run, _ = fake_nmcli("ethernet:unavailable\nwifi:connected\nloopback:connected (externally)\n")
    assert Wifi(run).connected()


def test_not_connected():
    run, _ = fake_nmcli("wifi:connecting (getting IP configuration)\n")
    assert not Wifi(run).connected()


def test_nmcli_failure_counts_as_not_connected():
    run, _ = fake_nmcli(None)
    assert not Wifi(run).connected()


def test_radio_on_off():
    run, calls = fake_nmcli("")
    wifi = Wifi(run)
    wifi.off()
    wifi.on()
    assert calls == [("radio", "wifi", "off"), ("radio", "wifi", "on")]

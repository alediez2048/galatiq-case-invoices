import invoice_processing


def test_package_importable():
    assert invoice_processing.__version__ == "0.1.0"

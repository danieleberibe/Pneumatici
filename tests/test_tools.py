import ipaddress
import ssl

import pytest

from scripts.evaluate_measurements import evaluate


def test_measurement_evaluation_computes_bias_error_and_repeatability(tmp_path):
    path = tmp_path / "measurements.csv"
    path.write_text(
        "point_id,x_true_m,y_true_m,z_true_m,x_m,y_m,z_m\na,0,0,1,0.003,0.004,1\na,0,0,1,0.003,0.004,1\n",
        encoding="utf-8",
    )
    report = evaluate(path)
    assert report["rmse_3d_mm"] == pytest.approx(5)
    assert report["bias_xyz_mm"] == pytest.approx([3, 4, 0])
    assert report["repeatability_std_xyz_mm"]["a"] == [0, 0, 0]


def test_measurement_evaluation_rejects_demo(tmp_path):
    path = tmp_path / "demo.csv"
    path.write_text("point_id,simulated\na,True\n", encoding="utf-8")
    with pytest.raises(ValueError, match="sintetiche"):
        evaluate(path)


def test_local_certificate_chain_and_private_key_load_without_installing_trust(tmp_path):
    x509 = pytest.importorskip("cryptography.x509")
    from scripts.make_certificate import make_certificates

    cert = make_certificates("192.168.1.10", tmp_path)
    ca = x509.load_pem_x509_certificate((tmp_path / "rootCA.crt").read_bytes())
    cert.verify_directly_issued_by(ca)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert ipaddress.ip_address("192.168.1.10") in san.get_values_for_type(x509.IPAddress)
    ssl.create_default_context(cafile=str(tmp_path / "rootCA.crt"))
    server = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server.load_cert_chain(tmp_path / "server.pem", tmp_path / "server-key.pem")
    with pytest.raises(ValueError, match="già presenti"):
        make_certificates("192.168.1.10", tmp_path)

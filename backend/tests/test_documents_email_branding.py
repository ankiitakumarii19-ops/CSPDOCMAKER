# -*- coding: utf-8 -*-
"""The documents email comes from Eko Bharat Ventures Pvt Ltd, with the
Eko logo inside it (No. 113, 15 Oct 2026)."""

import os

from app.services import email_service as es


class FakeSMTP:
    sent = []

    def __init__(self, *a, **k):
        pass

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)

    def quit(self):
        pass


def _send(monkeypatch, tmp_path):
    FakeSMTP.sent = []
    monkeypatch.setattr(es.settings, "email_method", "smtp")
    monkeypatch.setattr(es.smtplib, "SMTP", FakeSMTP)
    pdf = tmp_path / "CSP ID Card.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    assert es.send_documents_email("csp@example.com", "Shardha", "1A850254",
                                   ["CSP ID Card"], [str(pdf)])
    return FakeSMTP.sent[0]


def test_the_name_is_eko_bharat_ventures_everywhere():
    html = es._build_documents_html("Shardha", "1A850254", ["CSP ID Card"])
    plain = es._build_documents_plain("Shardha", "1A850254", ["CSP ID Card"])
    for text in (html, plain, es.documents_subject("1A850254")):
        assert "Eko Bharat Ventures Pvt Ltd" in text
        assert "EKO India" not in text
    assert es.documents_subject("1A850254") == (
        "Your CSP Documents — 1A850254 | Eko Bharat Ventures Pvt Ltd")


def test_the_logo_travels_inside_the_email(monkeypatch, tmp_path):
    msg = _send(monkeypatch, tmp_path)
    parts = list(msg.walk())
    images = [p for p in parts if p.get_content_type() == "image/png"]
    assert len(images) == 1 and images[0]["Content-ID"] == "<eko-logo>"
    html = next(p for p in parts if p.get_content_type() == "text/html")
    assert 'src="cid:eko-logo"' in html.get_payload(decode=True).decode()
    # The document is still an attachment, as before.
    assert any(p.get_filename() == "CSP ID Card.pdf" for p in parts)


def test_without_the_logo_file_the_email_still_goes(monkeypatch, tmp_path,
                                                    caplog):
    monkeypatch.setattr(es, "LOGO_PATH", os.path.join(str(tmp_path), "gone.png"))
    msg = _send(monkeypatch, tmp_path)
    assert not [p for p in msg.walk() if p.get_content_type() == "image/png"]
    html = next(p for p in msg.walk() if p.get_content_type() == "text/html")
    assert "cid:" not in html.get_payload(decode=True).decode()
    assert "could not be read" in caplog.text

import logging

import pytest

from beancount_no_amex import AmexAccountConfig, AmexConfig, Config, Importer
from beancount_no_amex.importer import Config as ModuleConfig
from beancount_no_amex.models import QboFileData, RawTransaction


def test_canonical_importer_api():
    assert ModuleConfig is Config
    assert AmexConfig is Config

    importer = Importer(Config(account_name="Liabilities:CreditCard:Amex"))

    assert importer.account_name == "Liabilities:CreditCard:Amex"


def test_deprecated_config_alias_warns():
    with pytest.warns(DeprecationWarning, match="AmexAccountConfig is deprecated"):
        config = AmexAccountConfig(account_name="Liabilities:CreditCard:Amex")

    assert isinstance(config, Config)


def test_debug_output_uses_logging_not_stderr(caplog, capsys):
    importer = Importer(Config(account_name="Liabilities:CreditCard:Amex"), debug=True)

    with caplog.at_level(logging.DEBUG, logger="beancount_no_amex.credit"):
        assert importer._determine_currency("SEK") == "SEK"

    assert "Using currency from file: SEK" in caplog.text
    assert capsys.readouterr().err == ""


def test_skipped_rows_warn_without_debug(caplog, monkeypatch):
    importer = Importer(Config(account_name="Liabilities:CreditCard:Amex"))
    monkeypatch.setattr(
        importer,
        "_parse_qbo_file",
        lambda _filepath: QboFileData(
            transactions=[
                RawTransaction(
                    date=None,
                    amount="-42.00",
                    payee="MISSING DATE",
                )
            ],
            currency="NOK",
        ),
    )

    with caplog.at_level(logging.WARNING, logger="beancount_no_amex.credit"):
        assert importer.extract("missing-date.qbo", []) == []

    assert "due to missing date" in caplog.text

import pytest

from beancount_no_amex import AmexAccountConfig, AmexConfig, Config, Importer
from beancount_no_amex.importer import Config as ModuleConfig


def test_canonical_importer_api():
    assert ModuleConfig is Config
    assert AmexConfig is Config

    importer = Importer(Config(account_name="Liabilities:CreditCard:Amex"))

    assert importer.account_name == "Liabilities:CreditCard:Amex"


def test_deprecated_config_alias_warns():
    with pytest.warns(DeprecationWarning, match="AmexAccountConfig is deprecated"):
        config = AmexAccountConfig(account_name="Liabilities:CreditCard:Amex")

    assert isinstance(config, Config)

from __future__ import annotations

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class _DummyS3Client:
    def head_bucket(self, **kwargs) -> None:
        return None

    def create_bucket(self, **kwargs) -> None:
        return None

    def upload_file(self, *args, **kwargs) -> None:
        return None

    def get_object(self, **kwargs):
        raise AssertionError("get_object should not be called in these tests")

    def put_object(self, **kwargs) -> None:
        return None


sys.modules.setdefault("boto3", types.SimpleNamespace(client=lambda *args, **kwargs: _DummyS3Client()))
sys.modules.setdefault("botocore", types.ModuleType("botocore"))
_botocore_config = types.ModuleType("botocore.config")
_botocore_config.Config = lambda *args, **kwargs: None
sys.modules.setdefault("botocore.config", _botocore_config)
_botocore_exceptions = types.ModuleType("botocore.exceptions")


class _DummyClientError(Exception):
    def __init__(self, response=None, operation_name=None):
        super().__init__("client error")
        self.response = response or {}


_botocore_exceptions.ClientError = _DummyClientError
sys.modules.setdefault("botocore.exceptions", _botocore_exceptions)


def _stub_module(module_name: str, class_name: str, crawler_name: str) -> None:
    module = types.ModuleType(module_name)
    crawler_cls = type(class_name, (), {"name": crawler_name})
    setattr(module, class_name, crawler_cls)
    sys.modules.setdefault(module_name, module)


_stub_module("concrete_crawlers.hazi_hinam", "HaziHinamCrawler", "hazi_hinam")
_stub_module("concrete_crawlers.shufersal", "ShufersalCrawler", "shufersal")
_stub_module("concrete_crawlers.super_pharm", "SuperPharmCrawler", "super_pharm")
_stub_module("concrete_crawlers.victory", "VictoryCrawler", "victory")
_stub_module("concrete_crawlers.wolt", "WoltCrawler", "wolt")

from concrete_crawlers.cerberus import CerberusCrawler
from crawler import InfraConfig
import orchestrator


class _RecordingCrawler(CerberusCrawler):
    instances: list["_RecordingCrawler"] = []

    def __init__(self, config):
        super().__init__(config)
        self.__class__.instances.append(self)

    def run(self) -> list[str]:
        return [f"{self.name}-result"]


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        _RecordingCrawler.instances.clear()

    def _infra(self) -> InfraConfig:
        tmpdir = Path(tempfile.mkdtemp())
        return InfraConfig(
            bucket="raw-prices",
            s3_endpoint=None,
            s3_access_key=None,
            s3_secret_key=None,
            s3_region=None,
            download_dir=tmpdir / "downloads",
        )

    def test_build_config_uses_registration_name_for_paths_and_env_overrides(self):
        infra = self._infra()
        settings = {
            "source_url": "https://url.publishedprices.co.il/login",
            "user_name": "RamiLevi",
            "password": "fallback",
        }

        with patch.dict(
            os.environ,
            {
                "CRAWLER_RAMI_LEVI_PASSWORD": "from-env",
                "CRAWLER_RAMI_LEVI_START_DATE": "20260805",
            },
            clear=False,
        ):
            config = orchestrator._build_config("rami_levi", settings, infra)

        self.assertEqual(config.name, "rami_levi")
        self.assertEqual(config.password, "from-env")
        self.assertEqual(config.start_date, "20260805")
        self.assertEqual(config.download_dir, infra.download_dir / "rami_levi")

    def test_build_config_passes_yohananof_start_date_into_crawler_config(self):
        infra = self._infra()
        settings = {
            "source_url": "https://url.publishedprices.co.il/login",
            "user_name": "yohananof",
            "password": "",
        }

        with patch.dict(
            os.environ,
            {"CRAWLER_YOHANANOF_START_DATE": "20260807"},
            clear=False,
        ):
            config = orchestrator._build_config("yohananof", settings, infra)

        self.assertEqual(config.name, "yohananof")
        self.assertEqual(config.start_date, "20260807")
        self.assertEqual(config.download_dir, infra.download_dir / "yohananof")

    def test_run_registers_both_cerberus_configurations_with_distinct_instance_names(self):
        registrations = [
            orchestrator.CrawlerRegistration(name="yohananof", crawler_cls=_RecordingCrawler),
            orchestrator.CrawlerRegistration(name="rami_levi", crawler_cls=_RecordingCrawler),
        ]

        with patch("orchestrator.load_infra_config", return_value=self._infra()):
            results = orchestrator.run(registrations)

        self.assertEqual(
            results,
            {
                "yohananof": ["yohananof-result"],
                "rami_levi": ["rami_levi-result"],
            },
        )
        self.assertEqual([crawler.name for crawler in _RecordingCrawler.instances], ["yohananof", "rami_levi"])
        self.assertTrue(str(_RecordingCrawler.instances[0].config.download_dir).endswith("yohananof"))
        self.assertTrue(str(_RecordingCrawler.instances[1].config.download_dir).endswith("rami_levi"))


if __name__ == "__main__":
    unittest.main()

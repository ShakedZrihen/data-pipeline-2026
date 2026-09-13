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

    def test_run_registers_all_cerberus_configurations_with_distinct_instance_names(self):
        registrations = [
            orchestrator.CrawlerRegistration(name="yohananof", crawler_cls=_RecordingCrawler),
            orchestrator.CrawlerRegistration(name="rami_levi", crawler_cls=_RecordingCrawler),
            orchestrator.CrawlerRegistration(name="tiv_taam", crawler_cls=_RecordingCrawler),
        ]

        with patch("orchestrator.load_infra_config", return_value=self._infra()):
            report = orchestrator.run(registrations)

        self.assertEqual(report.failed, [])
        self.assertEqual(
            report.uploaded,
            {
                "yohananof": ["yohananof-result"],
                "rami_levi": ["rami_levi-result"],
                "tiv_taam": ["tiv_taam-result"],
            },
        )
        self.assertEqual(
            [crawler.name for crawler in _RecordingCrawler.instances],
            ["yohananof", "rami_levi", "tiv_taam"],
        )
        self.assertTrue(str(_RecordingCrawler.instances[0].config.download_dir).endswith("yohananof"))
        self.assertTrue(str(_RecordingCrawler.instances[1].config.download_dir).endswith("rami_levi"))
        tiv_taam = _RecordingCrawler.instances[2]
        self.assertTrue(str(tiv_taam.config.download_dir).endswith("tiv_taam"))
        self.assertEqual(tiv_taam.config.user_name, "TivTaam")
        self.assertEqual(tiv_taam.config.password, "")


class SelectedCrawlersTests(unittest.TestCase):
    """``CRAWLER_PROVIDERS`` picks which chains a given runner attempts.

    Three of the eight sources refuse GitHub's datacenter IP ranges, so the
    hosted schedule has to skip them while a runner on an Israeli IP still runs
    all eight. Which chains are reachable is therefore a property of the
    *runner*, not of the code — which is why this is an environment variable
    and not an edit to ``CRAWLERS``. Deleting them from the list would break
    the only place they currently work.
    """

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

    def _names(self, crawlers) -> list[str]:
        return [orchestrator._registration_for(c).name for c in crawlers]

    def test_unset_runs_every_registered_crawler(self):
        """The default has to stay "all": a self-hosted runner sets nothing,
        and a chain must never become uncollected by omission."""
        environ = {k: v for k, v in os.environ.items() if k != "CRAWLER_PROVIDERS"}
        with patch.dict(os.environ, environ, clear=True):
            self.assertEqual(self._names(orchestrator.selected_crawlers()),
                             self._names(orchestrator.CRAWLERS))

    def test_empty_value_is_treated_as_unset(self):
        """An unset GitHub Actions variable renders as the empty string rather
        than being absent, so "" has to mean all, not none."""
        with patch.dict(os.environ, {"CRAWLER_PROVIDERS": "  "}, clear=False):
            self.assertEqual(self._names(orchestrator.selected_crawlers()),
                             self._names(orchestrator.CRAWLERS))

    def test_a_list_selects_those_crawlers_in_registration_order(self):
        with patch.dict(os.environ, {"CRAWLER_PROVIDERS": "wolt, yohananof"}, clear=False):
            self.assertEqual(self._names(orchestrator.selected_crawlers()),
                             ["yohananof", "wolt"])

    def test_blank_entries_are_ignored(self):
        with patch.dict(os.environ, {"CRAWLER_PROVIDERS": " wolt , , "}, clear=False):
            self.assertEqual(self._names(orchestrator.selected_crawlers()), ["wolt"])

    def test_an_unknown_name_fails_loudly_rather_than_silently_skipping(self):
        """A typo that quietly drops a chain is the exit-0 problem again: the
        job stays green while one source simply stops being collected."""
        with patch.dict(os.environ, {"CRAWLER_PROVIDERS": "wolt,shufresal"}, clear=False):
            with self.assertRaises(ValueError) as ctx:
                orchestrator.selected_crawlers()
        self.assertIn("shufresal", str(ctx.exception))

    def test_run_honours_the_selection(self):
        registrations = [
            orchestrator.CrawlerRegistration(name="yohananof", crawler_cls=_RecordingCrawler),
            orchestrator.CrawlerRegistration(name="rami_levi", crawler_cls=_RecordingCrawler),
        ]
        with patch.object(orchestrator, "CRAWLERS", registrations), \
             patch.object(orchestrator, "load_infra_config", return_value=self._infra()), \
             patch.dict(os.environ, {"CRAWLER_PROVIDERS": "rami_levi"}, clear=False):
            report = orchestrator.run()

        self.assertEqual(list(report.uploaded), ["rami_levi"])


class _FailingCrawler(CerberusCrawler):
    def run(self) -> list[str]:
        raise RuntimeError("login page changed")


class _QuietCrawler(CerberusCrawler):
    def run(self) -> list[str]:
        return []


class RunReportTests(unittest.TestCase):
    """A failed crawler and a crawler with nothing new are different outcomes.

    Until now both came back as ``[]``, and ``__main__`` exited 0 regardless,
    so a scheduled run stayed green for three weeks while three of eight
    sources failed on every run (#61). The report keeps the two apart and the
    entry point turns failures into a non-zero exit.
    """

    def _infra(self) -> InfraConfig:
        return InfraConfig(
            bucket="raw-prices",
            s3_endpoint=None,
            s3_access_key=None,
            s3_secret_key=None,
            s3_region=None,
            download_dir=Path(tempfile.mkdtemp()) / "downloads",
        )

    def _run(self, registrations):
        with patch("orchestrator.load_infra_config", return_value=self._infra()):
            return orchestrator.run(registrations)

    def test_a_failing_crawler_is_reported_as_failed_not_as_empty(self):
        report = self._run([
            orchestrator.CrawlerRegistration(name="yohananof", crawler_cls=_FailingCrawler),
        ])
        self.assertEqual(report.failed, ["yohananof"])
        self.assertNotIn("yohananof", report.uploaded)
        self.assertFalse(report.ok)

    def test_a_crawler_with_nothing_new_is_a_success(self):
        report = self._run([
            orchestrator.CrawlerRegistration(name="yohananof", crawler_cls=_QuietCrawler),
        ])
        self.assertEqual(report.uploaded, {"yohananof": []})
        self.assertEqual(report.failed, [])
        self.assertTrue(report.ok)

    def test_one_failure_does_not_stop_the_remaining_crawlers(self):
        _RecordingCrawler.instances.clear()
        report = self._run([
            orchestrator.CrawlerRegistration(name="yohananof", crawler_cls=_FailingCrawler),
            orchestrator.CrawlerRegistration(name="rami_levi", crawler_cls=_RecordingCrawler),
        ])
        self.assertEqual(report.failed, ["yohananof"])
        self.assertEqual(report.uploaded, {"rami_levi": ["rami_levi-result"]})

    def test_a_missing_configuration_is_a_failure_of_that_crawler_only(self):
        report = self._run([
            orchestrator.CrawlerRegistration(name="not_configured", crawler_cls=_RecordingCrawler),
            orchestrator.CrawlerRegistration(name="rami_levi", crawler_cls=_RecordingCrawler),
        ])
        self.assertEqual(report.failed, ["not_configured"])
        self.assertEqual(list(report.uploaded), ["rami_levi"])


class MainExitStatusTests(unittest.TestCase):
    """The process exit code is the only thing GitHub Actions looks at."""

    def test_exits_nonzero_when_any_crawler_failed(self):
        report = orchestrator.RunReport(
            uploaded={"wolt": ["a.gz"], "shufersal": []},
            failed=["hazi_hinam", "victory"],
        )
        with patch("orchestrator.run", return_value=report):
            self.assertEqual(orchestrator.main(), 1)

    def test_exits_zero_when_every_crawler_completed(self):
        report = orchestrator.RunReport(uploaded={"wolt": [], "shufersal": ["a.gz"]}, failed=[])
        with patch("orchestrator.run", return_value=report):
            self.assertEqual(orchestrator.main(), 0)


if __name__ == "__main__":
    unittest.main()

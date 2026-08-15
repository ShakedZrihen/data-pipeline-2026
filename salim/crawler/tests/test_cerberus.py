from __future__ import annotations

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

from concrete_crawlers.cerberus import CerberusCrawler
from crawler import Config


class _FakeResponse:
    def __init__(self, *, text: str = "", json_data: dict | None = None, status_code: int = 200):
        self.text = text
        self._json_data = json_data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self) -> dict:
        return self._json_data or {}


class _FakeSession:
    def __init__(self, *, get_responses: list[_FakeResponse], post_responses: list[_FakeResponse]):
        self.headers: dict[str, str] = {}
        self.get_calls: list[dict] = []
        self.post_calls: list[dict] = []
        self._get_responses = list(get_responses)
        self._post_responses = list(post_responses)

    def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return self._get_responses.pop(0)

    def post(self, url: str, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        return self._post_responses.pop(0)


class _StaticCerberusCrawler(CerberusCrawler):
    def __init__(self, config: Config, links: list[str], newest: str | None):
        super().__init__(config)
        self._links = links
        self._newest = newest

    def fetch(self) -> tuple[list[str], str | None]:
        return list(self._links), self._newest


class CerberusCrawlerTests(unittest.TestCase):
    def _config(
        self,
        *,
        name: str = "rami_levi",
        user_name: str = "RamiLevi",
        start_date: str | None = None,
    ) -> Config:
        tmpdir = Path(tempfile.mkdtemp())
        return Config(
            name=name,
            source_url="https://url.publishedprices.co.il/login",
            bucket="raw-prices",
            s3_endpoint=None,
            s3_access_key=None,
            s3_secret_key=None,
            s3_region=None,
            download_dir=tmpdir / name,
            link_suffixes=None,
            user_name=user_name,
            password="",
            start_date=start_date,
        )

    @staticmethod
    def _links() -> list[str]:
        return [
            "https://url.publishedprices.co.il/file/d/PriceFull7290058140886-001-20260804-235959.gz",
            "https://url.publishedprices.co.il/file/d/PriceFull7290058140886-001-20260805-010203.gz",
            "https://url.publishedprices.co.il/file/d/PromoFull7290058140886-001-20260806-121314.gz",
        ]

    def _run_cycle(
        self,
        *,
        start_date: str | None = None,
        checkpoint: str | None = None,
    ) -> tuple[list[str], _StaticCerberusCrawler]:
        crawler = _StaticCerberusCrawler(
            self._config(start_date=start_date),
            self._links(),
            newest="20260806121314",
        )
        crawler._cacher.load = lambda: checkpoint
        crawler._cacher.save = lambda date: None
        crawler._downloader.download = lambda links: [Path("/tmp") / links[0].rsplit("/", 1)[-1]]
        crawler._uploader.upload = lambda paths: [Path(paths[0]).name]
        return crawler.run(), crawler

    def test_fetch_logs_in_filters_files_sets_newest_and_reuses_authenticated_session(self):
        session = _FakeSession(
            get_responses=[
                _FakeResponse(text='<meta name="csrftoken" content="login-token">'),
                _FakeResponse(text='<meta name="csrftoken" content="listing-token">'),
            ],
            post_responses=[
                _FakeResponse(text="<html>ok</html>"),
                _FakeResponse(
                    json_data={
                        "aaData": [
                            {"type": "file", "fname": "PriceFull7290058140886-001-20260805-010203.gz"},
                            {"type": "file", "fname": "PromoFull7290058140886-001-20260806-121314.gz"},
                            {"type": "file", "fname": "StoresFull7290058140886-001-20260806-121314.gz"},
                            {"type": "dir", "fname": "archive"},
                        ],
                        "iTotalRecords": 4,
                    }
                ),
            ],
        )
        crawler = CerberusCrawler(self._config())

        with patch("concrete_crawlers.cerberus.requests.Session", return_value=session):
            links, newest = crawler.fetch()

        self.assertEqual(session.post_calls[0]["data"]["username"], "RamiLevi")
        self.assertEqual(
            links,
            [
                "https://url.publishedprices.co.il/file/d/PriceFull7290058140886-001-20260805-010203.gz",
                "https://url.publishedprices.co.il/file/d/PromoFull7290058140886-001-20260806-121314.gz",
            ],
        )
        self.assertEqual(newest, "20260806121314")
        self.assertIs(crawler._downloader.session, session)

    def test_new_links_returns_only_files_newer_than_checkpoint(self):
        crawler = CerberusCrawler(self._config())
        links = [
            "https://url.publishedprices.co.il/file/d/PriceFull7290058140886-001-20260805-010203.gz",
            "https://url.publishedprices.co.il/file/d/PromoFull7290058140886-001-20260806-121314.gz",
            "https://url.publishedprices.co.il/file/d/PriceFull7290058140886-001-20260804-235959.gz",
        ]

        fresh = crawler.new_links(links, "20260805010203")

        self.assertEqual(
            fresh,
            ["https://url.publishedprices.co.il/file/d/PromoFull7290058140886-001-20260806-121314.gz"],
        )

    def test_config_name_sets_instance_identity_for_logs_and_paths(self):
        crawler = CerberusCrawler(self._config(name="yohananof", user_name="yohananof"))

        self.assertEqual(crawler.name, "yohananof")
        self.assertEqual(crawler._log.name, "salim.crawler.yohananof")
        self.assertTrue(str(crawler.config.download_dir).endswith("yohananof"))
        self.assertEqual(crawler._uploader.key_prefix, "yohananof")
        self.assertEqual(crawler._cacher.key, "yohananof_last_run.txt")

    def test_run_without_start_date_or_checkpoint_downloads_all_links(self):
        uploaded, _ = self._run_cycle()

        self.assertEqual(
            uploaded,
            [
                "PriceFull7290058140886-001-20260804-235959.gz",
                "PriceFull7290058140886-001-20260805-010203.gz",
                "PromoFull7290058140886-001-20260806-121314.gz",
            ],
        )

    def test_run_with_start_date_and_no_checkpoint_is_inclusive(self):
        uploaded, _ = self._run_cycle(start_date="20260805")

        self.assertEqual(
            uploaded,
            [
                "PriceFull7290058140886-001-20260805-010203.gz",
                "PromoFull7290058140886-001-20260806-121314.gz",
            ],
        )

    def test_run_with_checkpoint_and_no_start_date_uses_checkpoint(self):
        uploaded, _ = self._run_cycle(checkpoint="20260805010203")

        self.assertEqual(
            uploaded,
            ["PromoFull7290058140886-001-20260806-121314.gz"],
        )

    def test_run_with_equal_start_date_and_checkpoint_does_not_recrawl_boundary(self):
        uploaded, _ = self._run_cycle(
            start_date="20260805010203",
            checkpoint="20260805010203",
        )

        self.assertEqual(
            uploaded,
            ["PromoFull7290058140886-001-20260806-121314.gz"],
        )

    def test_run_prefers_later_checkpoint_over_earlier_start_date(self):
        uploaded, _ = self._run_cycle(
            start_date="20260804",
            checkpoint="20260805010203",
        )

        self.assertEqual(
            uploaded,
            ["PromoFull7290058140886-001-20260806-121314.gz"],
        )

    def test_run_prefers_later_start_date_over_earlier_checkpoint(self):
        uploaded, _ = self._run_cycle(
            start_date="20260806",
            checkpoint="20260805010203",
        )

        self.assertEqual(
            uploaded,
            ["PromoFull7290058140886-001-20260806-121314.gz"],
        )

    def test_run_with_invalid_start_date_fails_clearly(self):
        crawler = _StaticCerberusCrawler(
            self._config(start_date="2026/08/not-a-date"),
            self._links(),
            newest="20260806121314",
        )
        crawler._cacher.load = lambda: None

        with self.assertRaisesRegex(
            ValueError,
            "date must use YYYYMMDD, YYYYMMDDHHMM, or YYYYMMDDHHMMSS",
        ):
            crawler.run()


if __name__ == "__main__":
    unittest.main()

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import URLError


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('ci_readiness', SCRIPTS / 'wait_for_http.py')
readiness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(readiness)


class TestReportGate(unittest.TestCase):
    def run_gate(self, content):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'report.xml'
            report.write_text(content)
            return subprocess.run([sys.executable, str(SCRIPTS / 'check_pytest_report.py'), str(report)],
                                  capture_output=True, text=True)

    def test_accepts_successful_pytest_and_browser_reports(self):
        result = self.run_gate('<testsuites><testsuite><testcase name="passed"/></testsuite></testsuites>')
        self.assertEqual(result.returncode, 0)
        self.assertIn('1 tests ran and passed', result.stdout)

    def test_rejects_skipped_failed_and_error_cases(self):
        for tag in ('skipped', 'failure', 'error'):
            with self.subTest(tag=tag):
                result = self.run_gate(f'<testsuites><testsuite><testcase name="bad"><{tag}/></testcase></testsuite></testsuites>')
                self.assertNotEqual(result.returncode, 0)

    def test_rejects_empty_and_malformed_reports(self):
        for content in ('<testsuites/>', 'invalid XML'):
            with self.subTest(content=content):
                self.assertNotEqual(self.run_gate(content).returncode, 0)


class TestReadiness(unittest.TestCase):
    def test_retries_until_http_200_without_reading_response_body(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(readiness, 'urlopen', side_effect=[URLError('not ready'), response]) as fetch:
            with patch.object(readiness.time, 'sleep'):
                self.assertTrue(readiness.wait_for_http('http://127.0.0.1/health', 1))
        self.assertEqual(fetch.call_count, 2)
        response.read.assert_not_called()

    def test_stops_at_deadline_without_a_network_call(self):
        with patch.object(readiness.time, 'monotonic', side_effect=[0, 2]):
            with patch.object(readiness, 'urlopen') as fetch:
                self.assertFalse(readiness.wait_for_http('http://127.0.0.1/health', 1))
        fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()

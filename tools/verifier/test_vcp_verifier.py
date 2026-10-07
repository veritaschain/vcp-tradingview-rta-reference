"""Regression tests for honest evidence assessment, using only the stdlib."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / 'tools/verifier/vcp_verifier.py'
EVENTS = ROOT / 'evidence/01_trade_logs/vcp_tv_events.jsonl'
SECURITY = ROOT / 'evidence/04_anchor/security_object.json'
ANCHOR = ROOT / 'evidence/04_anchor/anchor_reference.json'


class EvidenceAssessmentTests(unittest.TestCase):
    def run_verifier(self, events=EVENTS, security=SECURITY, anchor=ANCHOR, extra=()):
        args = [sys.executable, str(VERIFIER), str(events)]
        if security is not None:
            args += ['-s', str(security)]
        if anchor is not None:
            args += ['-a', str(anchor)]
        return subprocess.run(args + list(extra), capture_output=True, text=True)

    def test_local_anchor_never_establishes_silver(self):
        result = self.run_verifier()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn('Checked Internal Integrity: [PASS]', result.stdout)
        self.assertIn('[LOCAL_ONLY]', result.stdout)
        self.assertIn('Silver External-Anchor Requirement: [NOT MET]', result.stdout)
        self.assertNotIn('Overall Status: [PASS]', result.stdout)
        self.assertIn('Digital Signatures and Signer Identity: [NOT VERIFIED]', result.stdout)

    def test_explicit_integrity_mode_is_not_conformance_success(self):
        result = self.run_verifier(extra=['--integrity-only'])
        self.assertEqual(result.returncode, 0)
        self.assertIn('SILVER NOT ESTABLISHED', result.stdout)

    def test_missing_anchor_is_incomplete(self):
        result = self.run_verifier(anchor=None)
        self.assertEqual(result.returncode, 2)
        self.assertIn('[NOT_PROVIDED]', result.stdout)

    def test_missing_security_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_verifier(security=Path(tmp)/'missing.json')
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('[PASS]', result.stdout)

    def test_no_security_discloses_unchecked_root(self):
        result = self.run_verifier(security=None)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Merkle Root: [NOT CHECKED]', result.stdout)

    def test_external_names_or_pending_metadata_are_not_proof(self):
        for kind in ['opentimestamps', 'bitcoin', 'rfc3161_tsa', 'unknown']:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                obj = json.loads(ANCHOR.read_text())
                obj.update(anchor_type=kind, pending=True, status='confirmed', confirmations=6)
                path = Path(tmp)/'anchor.json'; path.write_text(json.dumps(obj))
                result = self.run_verifier(anchor=path)
                self.assertEqual(result.returncode, 2)
                self.assertIn('[UNVERIFIED]', result.stdout)

    def test_wrong_anchor_root_fails_even_in_integrity_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            obj=json.loads(ANCHOR.read_text()); obj['merkle_root']='0'*64
            path=Path(tmp)/'anchor.json'; path.write_text(json.dumps(obj))
            for extra in [[], ['--integrity-only']]:
                result=self.run_verifier(anchor=path, extra=extra)
                self.assertEqual(result.returncode, 1)
                self.assertIn('[INVALID]', result.stdout)

    def test_malformed_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'broken.json'
            for bad in ['{', '[]', 'null', '{}']:
                path.write_text(bad)
                for field in ['security', 'anchor']:
                    with self.subTest(field=field, bad=bad):
                        result=self.run_verifier(**{field:path})
                        self.assertEqual(result.returncode, 1)

    def test_corrupt_event_line_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'events.jsonl'
            path.write_text(EVENTS.read_text()+'{broken json}\n')
            result=self.run_verifier(events=path)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('[PASS]', result.stdout)

    def test_wrong_count_or_root_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'security.json'
            for field, value in [('event_count', 39), ('merkle_root', '0'*64)]:
                obj=json.loads(SECURITY.read_text()); obj[field]=value
                path.write_text(json.dumps(obj))
                result=self.run_verifier(security=path)
                self.assertEqual(result.returncode, 1)

    def test_tampered_events_fail(self):
        result=self.run_verifier(events=ROOT/'evidence/03_tamper_detection/tampered_chain.jsonl')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Checked Internal Integrity: [FAIL]', result.stdout)

    def test_saved_report_is_reproducible(self):
        args=json.loads((ROOT/'evidence/evidence_index.json').read_text())['verification']['command'].split()
        args[0]=sys.executable
        result=subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout,(ROOT/'evidence/02_verification/verification_report.txt').read_text())

    def test_metadata_does_not_invent_creation_time(self):
        pack=json.loads((ROOT/'evidence/evidence_index.json').read_text())['evidence_pack']
        self.assertIsNone(pack['created_at'])
        self.assertEqual(pack['metadata_correction']['previous_created_at'],'2025-01-17T00:00:00Z')
        self.assertEqual(pack['assessment_status'],'SILVER_NOT_ESTABLISHED')


class SimulatedProviderTests(unittest.TestCase):
    def test_external_stubs_cannot_verify_or_confirm(self):
        # Avoid importing the sidecar package's unrelated runtime dependencies.
        spec=importlib.util.spec_from_file_location('anchor_under_test',ROOT/'sidecar/anchor.py')
        module=importlib.util.module_from_spec(spec)
        sys.modules[spec.name]=module; spec.loader.exec_module(module)
        async def check():
            for provider in [module.OpenTimestampsProvider(),module.BitcoinProvider(),module.TSAProvider()]:
                result=await provider.anchor(b'\x01'*32)
                self.assertFalse(result.success)
                self.assertTrue(result.proof['simulated'])
                self.assertFalse(await provider.verify(b'\x01'*32,result.proof))
                self.assertEqual((await provider.get_status(result.anchor_id))['status'],'unverified')
        asyncio.run(check())


if __name__ == '__main__':
    unittest.main()

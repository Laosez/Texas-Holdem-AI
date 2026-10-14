"""Reliability tests for A17 catalog, safe Railway settings, checkpoint resume and backup lifecycle."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import bots
import replit_simulator as app
import export_preflop_ranges_v4 as exporter
from bots.a17_ranges import A17_HAND_TO_BOX, CATALOG_ID
from bots.a17_ranges_legacy import A17_HAND_TO_BOX as LEGACY


class ReliabilityTests(unittest.TestCase):
    def test_canonical_a17_and_frozen_legacy(self):
        self.assertEqual(CATALOG_ID, "A17_V5")
        self.assertEqual(len(A17_HAND_TO_BOX), 169)
        self.assertEqual(len(LEGACY), 169)
        self.assertEqual({h for h in A17_HAND_TO_BOX if A17_HAND_TO_BOX[h] != LEGACY[h]},
                         {"JTo", "J9o"})
        for hand in ("JTo", "J9o"):
            self.assertEqual(A17_HAND_TO_BOX[hand], 14)
            self.assertEqual(LEGACY[hand], 10)
        self.assertIsNotNone(bots.create_bot("a17_preflop_legacy"))
        self.assertIsNotNone(bots.create_bot("split:a17_preflop_legacy:tag_punisher"))

    def test_catalog_and_version_fingerprint(self):
        c = app.strategy_catalog()
        self.assertEqual(c["a17_version"], "A17_V5")
        self.assertIn("a17_preflop_legacy", c["strategies"])
        self.assertEqual(len(c["code_fingerprint"]), 64)

    def test_railway_rejects_unsafe_parallel(self):
        with patch.dict("os.environ", {"RAILWAY_PROJECT_ID": "unit-test"}):
            with self.assertRaisesRegex(ValueError, "1 процесс"):
                app.validate_config({"parallel": 2})
            self.assertEqual(app.validate_config({"parallel": 1})["parallel"], 1)

    def test_checkpoint_writes_once_and_reuses(self):
        task = (1, ["gto", "smart"], 500, 1, 2, 50, 10000, 42, 0)
        result = (1, 42, 0, {"status": "completed", "hand_count": 1}, [], [])
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with patch.object(exporter, "run_one", return_value=result) as runner:
                self.assertEqual(exporter.task_checkpoint(task, root, "exact-config"), result)
                self.assertEqual(exporter.task_checkpoint(task, root, "exact-config"), list(result))
                runner.assert_called_once()
                self.assertTrue((root / "000001.json.gz").is_file())

    def test_soft_delete_restores_files_and_result(self):
        with tempfile.TemporaryDirectory() as td, patch.object(app, "OUT", Path(td)):
            run_id = "20261014_audit"
            folder = Path(td) / run_id
            folder.mkdir()
            job = {"id": run_id, "status": "completed", "config": {},
                   "created": app.now(), "updated": app.now(), "returncode": 0,
                   "log": [], "report": {"leaderboard": []}}
            app.RUNS[run_id] = job
            try:
                app.persist(job)
                app.delete_session(run_id)
                self.assertFalse(folder.exists())
                self.assertTrue((Path(td) / ".trash" / run_id / "job.json").is_file())
                restored = app.restore_deleted(run_id)
                self.assertEqual(restored["id"], run_id)
                self.assertTrue(folder.exists())
            finally:
                app.RUNS.pop(run_id, None)

    def test_partial_checkpoint_archive_roundtrip(self):
        config = app.validate_config({"bots": [{"pre": "gto", "post": "gto"}, {"pre": "gto", "post": "gto"}]})
        with tempfile.TemporaryDirectory() as td, patch.object(app, "OUT", Path(td)):
            original_id = "20261014_partial"
            folder = Path(td) / original_id
            checkpoint = folder / "_checkpoints"
            checkpoint.mkdir(parents=True)
            (checkpoint / "config.json").write_text(json.dumps({"config_key": "abc"}))
            (folder / "simulation.log").write_text("1/90 tournaments\\nStopped due to crash\\n")
            job = {"id": original_id, "created": app.now(), "updated": app.now(),
                   "config": config, "status": "failed", "returncode": 1,
                   "report": None, "stats": {}, "progress": {"done": 1, "total": 90},
                   "performance": None, "strategy_fingerprint": app.strategy_fingerprint(),
                   "log": ["Stopped due to crash"]}
            app.RUNS[original_id] = job
            try:
                data = app.zip_results(job)
                archive = zipfile.ZipFile(io.BytesIO(data))
                self.assertIn("_checkpoints/config.json", archive.namelist())
                self.assertIn("session_manifest.json", archive.namelist())
                imported = app.import_session(data)
                self.assertEqual(imported["status"], "interrupted")
                self.assertIn("Stopped due to crash", "\\n".join(imported["log"]))
                self.assertEqual(imported["strategy_fingerprint"], app.strategy_fingerprint())
            finally:
                for job_id in list(app.RUNS):
                    if job_id == original_id or job_id.startswith("import_"):
                        app.RUNS.pop(job_id, None)

    def test_integrity_file_detects_tampering(self):
        with tempfile.TemporaryDirectory() as td, patch.object(app, "OUT", Path(td)):
            directory = Path(td) / "20261014_integrity"
            directory.mkdir()
            file = directory / "test.csv"
            file.write_text("a,b\\n1,2\\n")
            app.write_integrity_manifest(directory)
            manifest = json.loads((directory / "integrity.json").read_text())
            self.assertEqual(manifest["files"]["test.csv"], app.sha256_file(file))
            file.write_text("changed")
            check = app.audit_session({"id": directory.name, "status": "cancelled"})
            self.assertFalse(check["ok"])
            self.assertTrue(any("SHA-256" in line for line in check["observations"]))

    def test_integrity_zip_roundtrip_validated(self):
        with tempfile.TemporaryDirectory() as td, patch.object(app, "OUT", Path(td)):
            folder = Path(td) / "20261014_checksum"
            folder.mkdir()
            (folder / "tournament_report.json").write_text(json.dumps({"leaderboard": []}))
            (folder / "simulation.log").write_text("correct log")
            app.write_integrity_manifest(folder)
            job = {"id": folder.name, "config": {}, "created": app.now(),
                   "status": "completed", "strategy_fingerprint": app.strategy_fingerprint()}
            archive = app.zip_results(job)
            old = dict(app.RUNS)
            try:
                imported = app.import_session(archive)
                self.assertEqual(imported["status"], "imported")
                corrupted = io.BytesIO()
                with zipfile.ZipFile(io.BytesIO(archive)) as source, zipfile.ZipFile(corrupted, "w") as output:
                    for entry in source.infolist():
                        payload = source.read(entry.filename)
                        if entry.filename == "simulation.log":
                            payload = b"malicious modification"
                        output.writestr(entry.filename, payload)
                with self.assertRaisesRegex(ValueError, "Контрольная сумма"):
                    app.import_session(corrupted.getvalue())
            finally:
                app.RUNS.clear()
                app.RUNS.update(old)

    def test_old_unversioned_run_cannot_resume(self):
        run_id = "20261014_unversioned"
        app.RUNS[run_id] = {"id": run_id, "status": "failed", "config": {"players": ["a17_tag", "gto"]}}
        try:
            with self.assertRaisesRegex(RuntimeError, "Версия"):
                app.resume_run(run_id)
        finally:
            app.RUNS.pop(run_id, None)


if __name__ == "__main__":
    unittest.main()

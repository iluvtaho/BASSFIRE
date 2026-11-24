import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from bassfire_comp.config import load_config
from bassfire_comp.pipeline import run

DEMO = Path(__file__).resolve().parent.parent / "bassfire_comp" / "demo_data"


def read(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_demo_behaviour(self):
        out = self.tmp / "o"
        s = run(DEMO, out, load_config(None))
        self.assertEqual((s["references"], s["targets"]), (6, 3))
        pairs = read(out / "pairwise_comparability.csv")
        tiers = {(p["reference_experiment_id"], p["target_experiment_id"]): p["eligibility_tier"]
                 for p in pairs}
        self.assertEqual(tiers[("SYN-B2-01", "SYN-S1-01")], "direct")
        self.assertEqual(tiers[("SYN-B1-01", "SYN-S1-01")], "ineligible")   # flow mismatch
        self.assertEqual(tiers[("SYN-B2-04", "SYN-S1-01")], "needs_review")  # flow unknown
        self.assertEqual(tiers[("SYN-B2-03", "SYN-S1-01")], "exploratory")   # related fuel
        planned = read(out / "planned_experiments.csv")
        self.assertEqual([r["experiment_id"] for r in planned], ["SYN-S4-01"])
        executed_ids = {r["experiment_id"] for r in read(out / "executed_experiments.csv")}
        self.assertNotIn("SYN-S4-01", executed_ids)
        self.assertEqual(len(read(out / "excluded_records.csv")), 1)
        top = {r["target_experiment_id"]: r for r in read(out / "top_matches_by_saffire.csv")
               if r["rank"] in ("", "1")}
        self.assertEqual(top["SYN-S2-01"]["outcome"], "no_qualifying_match")

    def test_exploratory_tier_can_be_switched_off(self):
        cfg = load_config(None)
        cfg["eligibility"]["exploratory_tier_enabled"] = False
        out = self.tmp / "o"
        run(DEMO, out, cfg)
        tiers = {p["eligibility_tier"] for p in read(out / "pairwise_comparability.csv")}
        self.assertNotIn("exploratory", tiers)

    def test_deterministic_csvs(self):
        a, b = self.tmp / "a", self.tmp / "b"
        run(DEMO, a, load_config(None))
        run(DEMO, b, load_config(None))
        for name in ("pairwise_comparability.csv", "top_matches_by_saffire.csv",
                     "executed_experiments.csv"):
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)

    def test_raw_autodetect_from_psi_folder(self):
        data = self.tmp / "data"
        (data / "raw" / "PSI-25" / "tables").mkdir(parents=True)
        (data / "raw" / "PSI-98").mkdir(parents=True)
        (data / "raw" / "PSI-25" / "tables" / "runs.csv").write_text(
            "Run,Fuel,Flow Direction,Gravity,Flow speed (cm/s),O2 (volume_percent)\n"
            "1,SIBAL,concurrent,microgravity,20,21\n", encoding="utf-8")
        (data / "raw" / "PSI-98" / "saffire_runs.csv").write_text(
            "Run,Fuel,Flow Direction,Gravity,Flow speed (cm/s),O2 (volume_percent)\n"
            "1,SIBAL,concurrent,microgravity,20,21\n", encoding="utf-8")
        (data / "raw" / "PSI-98" / "sensor.csv").write_text(
            "time,temp_c,pressure_kpa\n0,21,101\n1,21,101\n", encoding="utf-8")
        out = self.tmp / "o"
        s = run(data, out, load_config(None))
        self.assertEqual((s["references"], s["targets"]), (1, 1))
        ex = read(out / "executed_experiments.csv")
        self.assertTrue(all("status_assumed_from_psi_repository" in r["flags"] for r in ex))
        inv = {r["path"]: r["detected_as"] for r in read(out / "source_inventory.csv")}
        self.assertEqual(inv["raw/PSI-98/sensor.csv"], "not parsed")

    def test_empty_data_dir_runs_cleanly(self):
        data = self.tmp / "data"
        data.mkdir()
        s = run(data, self.tmp / "o", load_config(None))
        self.assertEqual(s["pairs"], 0)
        self.assertIn("No pairs could be formed", (self.tmp / "o" / "run_report.md").read_text())

    def test_xlsx_curated_table(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        data = self.tmp / "data"
        (data / "runs").mkdir(parents=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["programme", "experiment_id", "record_status", "fuel_name", "flow_direction"])
        ws.append(["SAFFIRE-I", "X1", "executed", "SIBAL", "concurrent"])
        wb.save(data / "runs" / "t.xlsx")
        run(data, self.tmp / "o", load_config(None))
        ids = [r["record_id"] for r in read(self.tmp / "o" / "executed_experiments.csv")]
        self.assertEqual(ids, ["SAFFIRE-I:X1"])


if __name__ == "__main__":
    unittest.main()

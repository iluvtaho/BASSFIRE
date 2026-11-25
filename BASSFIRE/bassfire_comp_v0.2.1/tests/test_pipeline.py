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

    def test_real_layout_roster_merge_and_non_run_rows(self):
        data = self.tmp / "data"
        (data / "raw").mkdir(parents=True)
        (data / "runs").mkdir(parents=True)
        # BASS-like roster: no flow / O2 columns; quoted inch mark; duplicate ids; cleaning line
        (data / "raw" / "PSI-26_Experimental_table_BASS.csv").write_text(
            "Date,GMT,As Run Test #,Test #,Sample #,Fuel Sample Material\r\n"
            "3/30/2012,90,1,7,10,SIBAL 2 cm\r\n"
            "3/30/2012,90,2,8,11,\"1/4\"\" clear rod\"\r\n"
            "4/1/2012,91,3,9,12,PMMA 2 cm\r\n"
            "4/1/2012,91,4,9,13,PMMA 2 cm\r\n"
            "8/3/2012,216,,,,SOOT Cleaning\r\n", encoding="utf-8")
        (data / "raw" / "PSI-98_Experimental_table_SAFFIRE-1.csv").write_text(
            "Sample Number ,Material,Sample Thickness (cm),Sample Length (cm),Sample Width (cm),"
            "Air Flow (cm/s),Percent O2,Flow Direction \r\n"
            "S1,SIBAL Fabric,0.37,40.6,94,20,21.5 - 21.7,Concurrent\r\n"
            "F1C1/F1C2,Pre-test flow visulation data for sample 1,,,,,,\r\n", encoding="utf-8")
        (data / "runs" / "bass_curated.csv").write_text(
            "programme,experiment_id,airflow_value,airflow_unit,airflow_measurement_type,"
            "flow_direction,oxygen_value,oxygen_unit_or_basis\n"
            "BASS,7,20,cm/s,inlet,concurrent,21,volume_percent\n", encoding="utf-8")
        out = self.tmp / "o"
        s = run(data, out, load_config(None))
        ex = {r["record_id"]: r for r in read(out / "executed_experiments.csv")}
        self.assertEqual(ex["BASS:7"]["flow_direction"], "concurrent")          # curated over raw
        self.assertEqual(ex["BASS:7"]["fuel_identity"], "SIBAL")                 # kept from raw
        self.assertIn("merged_curated_over_raw_table", ex["BASS:7"]["flags"])
        self.assertAlmostEqual(float(ex["BASS:7"]["airflow_si"]), 0.2)
        self.assertEqual(ex["BASS:8"]["fuel_name"], '1/4" clear rod')            # quote preserved
        dup = [k for k in ex if k.startswith("BASS:9#")]
        self.assertEqual(len(dup), 2)                                            # both kept, disambiguated
        reasons = " ".join(r["exclusion_reason"] for r in read(out / "excluded_records.csv"))
        self.assertIn("non_run_row", reasons)
        self.assertIn("missing_experiment_id", reasons)
        self.assertAlmostEqual(float(ex["SAFFIRE-I:S1"]["oxygen_mole_fraction_si"]), 0.216)
        self.assertIn("oxygen_basis_from_config", ex["SAFFIRE-I:S1"]["flags"])
        self.assertEqual(ex["SAFFIRE-I:S1"]["airflow_measurement_type"], "inlet")
        todo = read(out / "todo_fill_in.csv")
        by_id = {(r["programme"], r["experiment_id"]): r for r in todo}
        self.assertIn("flow_direction", by_id[("BASS", "8")]["ref_missing"])
        self.assertIn("default_from_config:gravity_environment", ex["BASS:7"]["flags"])

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

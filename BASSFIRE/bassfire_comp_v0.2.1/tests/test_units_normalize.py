import unittest

from bassfire_comp import units as U
from bassfire_comp.config import load_config
from bassfire_comp.normalize import build_record, parse_cell


class UnitsTest(unittest.TestCase):
    def test_velocity_and_length(self):
        self.assertAlmostEqual(U.to_velocity_ms(20, "cm/s")[0], 0.2)
        self.assertAlmostEqual(U.to_velocity_ms(60, "ft/min")[0], 0.3048)
        self.assertAlmostEqual(U.to_length_m(50, "mm")[0], 0.05)

    def test_temperature_and_pressure(self):
        self.assertAlmostEqual(U.to_temperature_k(21, "C")[0], 294.15)
        self.assertAlmostEqual(U.to_pressure_pa(1, "atm")[0], 101325.0)
        self.assertEqual(U.to_pressure_pa(14.7, "psig")[3], "gauge")

    def test_unknown_unit_raises(self):
        with self.assertRaises(U.UnitError):
            U.to_velocity_ms(1, "L/min")


class NormalizeTest(unittest.TestCase):
    cfg = load_config(None)

    def test_parse_cell_reasons(self):
        self.assertEqual(parse_cell("")[1], "not_extracted")
        self.assertEqual(parse_cell("n/a")[1], "not_reported")
        self.assertEqual(parse_cell("not_reported")[1], "not_reported")
        self.assertEqual(parse_cell("10 and 20")[1], "ambiguous_definition")
        self.assertEqual(parse_cell("037 mm")[1], "ambiguous_definition")   # typo guard, not 37 mm
        self.assertEqual(parse_cell("See Fig. 5")[1], "ambiguous_definition")
        self.assertEqual(parse_cell("12.5"), (12.5, None))

    def _rec(self, **f):
        base = {"programme": "BASS-II", "fuel_name": "SIBAL"}
        base.update(f)
        return build_record(base, {}, self.cfg)

    def test_percent_without_basis_is_ambiguous(self):
        r = self._rec(oxygen_value="21", oxygen_unit_or_basis="percent")
        self.assertFalse(r.q["oxygen_mole_fraction"].known)
        self.assertIn("oxygen_basis_unspecified", r.flags)

    def test_volume_percent_and_derived_partial_pressure(self):
        r = self._rec(oxygen_value="21", oxygen_unit_or_basis="volume_percent",
                      pressure_value="100", pressure_unit="kPa", pressure_basis="absolute")
        self.assertAlmostEqual(r.q["oxygen_mole_fraction"].si_value, 0.21)
        self.assertAlmostEqual(r.q["oxygen_partial_pressure"].si_value, 21000.0)

    def test_gauge_pressure_not_converted(self):
        r = self._rec(pressure_value="5", pressure_unit="psig")
        self.assertFalse(r.q["pressure"].known)
        self.assertIn("pressure_gauge_not_absolute", r.flags)

    def test_missing_unit_not_guessed(self):
        r = self._rec(airflow_value="20")
        self.assertFalse(r.q["airflow"].known)
        self.assertIn("airflow_unit_missing", r.flags)

    def test_ratio_needs_named_denominator(self):
        r = self._rec(sample_width="50", duct_width="200", dimension_unit="mm")
        self.assertFalse(r.q["sample_duct_width_ratio"].known)
        self.assertIn("ratio_denominator_missing", r.flags)
        r2 = self._rec(sample_width="50", duct_width="200", dimension_unit="mm",
                       ratio_denominator="duct_width")
        self.assertAlmostEqual(r2.q["sample_duct_width_ratio"].si_value, 0.25)

    def test_dimension_definitions_flagged_by_default(self):
        self.assertIn("dimension_definitions_unreviewed", self._rec().flags)
        self.assertNotIn("dimension_definitions_unreviewed",
                         self._rec(dimension_definition_status="verified").flags)

    def test_header_unit_used(self):
        r = build_record({"programme": "BASS", "airflow_value": "20"},
                         {"airflow_value": "cm/s"}, self.cfg)
        self.assertAlmostEqual(r.q["airflow"].si_value, 0.2)


class RealWorldFormatsTest(unittest.TestCase):
    cfg = load_config(None)

    def _rec(self, **f):
        base = {"programme": "SAFFIRE-III", "investigation_id": "PSI-100"}
        base.update(f)
        return build_record(base, {}, self.cfg)

    def test_units_inside_cells(self):
        r = self._rec(airflow_value="30 cm/s", sample_thickness=".33 cm", sample_length="94 cm")
        self.assertAlmostEqual(r.q["airflow"].si_value, 0.3)
        self.assertAlmostEqual(r.q["sample_thickness"].si_value, 0.0033)
        self.assertAlmostEqual(r.q["sample_length"].si_value, 0.94)

    def test_leading_zero_thickness_not_read_as_37_mm(self):
        r = self._rec(sample_thickness="037 mm")
        self.assertFalse(r.q["sample_thickness"].known)
        self.assertEqual(r.q["sample_thickness"].missing_reason, "ambiguous_definition")

    def test_range_and_tilde(self):
        r = self._rec(oxygen_value="21.5 - 21.7", oxygen_unit_or_basis="volume_percent")
        self.assertAlmostEqual(r.q["oxygen_mole_fraction"].si_value, 0.216)
        self.assertIn("oxygen_range_midpoint_used", r.flags)
        r2 = self._rec(oxygen_value="~ 21.5", oxygen_unit_or_basis="volume_percent")
        self.assertIn("oxygen_approximate_value", r2.flags)

    def test_oxygen_basis_from_config(self):
        cfg = load_config(None)
        cfg["ingest"]["oxygen_basis_by_investigation"] = {"PSI-98": "volume_percent"}
        r = build_record({"programme": "SAFFIRE-I", "investigation_id": "PSI-98",
                          "oxygen_value": "21.5"}, {"oxygen_value": "percent"}, cfg)
        self.assertAlmostEqual(r.q["oxygen_mole_fraction"].si_value, 0.215)
        self.assertIn("oxygen_basis_from_config", r.flags)

    def test_material_string_parsing(self):
        r = self._rec(programme="BASS-II", fuel_name="1 cm wide 200 micron thick PMMA")
        self.assertAlmostEqual(r.q["sample_width"].si_value, 0.01)
        self.assertAlmostEqual(r.q["sample_thickness"].si_value, 2e-4)
        self.assertEqual(r.text["fuel_identity"], "PMMA")
        s = self._rec(programme="BASS-II", fuel_name="2 cm SIBAL")
        self.assertAlmostEqual(s.q["sample_width"].si_value, 0.02)
        self.assertEqual(s.text["sample_shape"], "fabric")
        sp = self._rec(programme="BASS", fuel_name="PMMA sphere 2 cm")
        self.assertFalse(sp.q["sample_width"].known)          # a sphere's cm is a diameter
        self.assertEqual(sp.text["sample_shape"], "sphere")
        op = self._rec(programme="BASS", fuel_name="SIBAL 2 cm   opposed flow ")
        self.assertEqual(op.text["flow_direction"], "opposed")

    def test_composite_sample_flagged(self):
        r = self._rec(fuel_name="PMMA & Nomex")
        self.assertIn("fuel_composite_sample", r.flags)


if __name__ == "__main__":
    unittest.main()

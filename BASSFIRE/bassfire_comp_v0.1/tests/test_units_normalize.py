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
        self.assertEqual(parse_cell("10-20")[1], "ambiguous_definition")
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


if __name__ == "__main__":
    unittest.main()

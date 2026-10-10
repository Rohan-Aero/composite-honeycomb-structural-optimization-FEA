import unittest

from plm import ingest, units

DECK = """/prep7
nblock,3,,4
(1i9,3e20.9e3)
        1    0.000000000E+00    0.000000000E+00    0.000000000E+00
        2    2.000000000E+00    0.000000000E+00    0.000000000E+00
        3    2.000000000E+00    3.000000000E+00    0.000000000E+00
        4    0.000000000E+00    3.000000000E+00    0.000000000E+00
-1
et,1,186
eblock,19,solid,,1
(19i9)
        1        1        1        1        0        0        0        0       20        0        1        1
MP,DENS,1,1.25e-09,	! tonne mm^-3
MP,EX,1,3500,	! tonne s^-2 mm^-1
MP,NUXY,1,0.36,
MP,UVID,1,abc-123
CMBLOCK,_FIXEDSU,NODE,       2
et,8,154
eblock,10,,,1
(15i9)
        9        8        8        8       12        1        2        3        4        0        0        0        0
sfe,all,1,pres,1,0.
sfe,all,3,pres,1,-0.5
"""
SOLVE = """ RELEASE= 2025 R1              BUILD= 25.1      UP20241202   VERSION=WINDOWS x64
 CURRENT JOBNAME=file0  17:58:01  APR 29, 2025 CP=      0.109
 --- Number of total nodes = 14009
 --- Number of solid elements = 2093
 --- Number of total elements = 3952
   ANALYSIS TYPE . . . . . . . . . . . . . . . . .STATIC (STEADY-STATE)
   TOTAL MASS = 0.41041E-04
  *** MASS SUMMARY BY ELEMENT TYPE ***

  TYPE      MASS
     1  0.274880E-04
     2  0.677634E-05
 NUMBER OF WARNING MESSAGES ENCOUNTERED=          2
 NUMBER OF ERROR   MESSAGES ENCOUNTERED=          0
"""
MNTR = """  LOAD   SUB-  NO.  NO.    TOTL  INCREMENT    TOTAL         VARIAB 1     VARIAB 2     VARIAB 3     VARIAB 4
                                                             Wall         MxDs         MxPl         MxRe

     1      1    1     1      1     1.0000       1.0000      0.71493     -0.68005E-02   0.0000       0.0000
"""
README = """# Title here

## Objective
One sentence objective.

## Detailed Results

| Thickness | Deformation (mm) | Von Mises Stress (MPa) | Elastic Strain |
|-----------|-----------------|------------------------|----------------|
| 0.85 mm   | 0.00701         | 2.9896                 | 0.000896       |
| 1.2 mm    | 0.00601         | 2.9189                 | 0.000876       |

**note**
"""


class ParserTests(unittest.TestCase):
    def test_parse_ds(self):
        ds = ingest.parse_ds(DECK)
        self.assertEqual(ds["materials"][1]["EX"][0], "3500")
        self.assertEqual(ds["type_material"][1][0], 1)
        self.assertEqual(ds["fixed_nodes"][0], 2)
        self.assertEqual(ds["pressure"][0], -0.5)
        self.assertAlmostEqual(ds["area_mm2"], 6.0)  # 2 x 3 rectangle from its diagonals
        self.assertEqual(ds["n_surface"], 1)

    def test_parse_solve_out(self):
        so = ingest.parse_solve_out(SOLVE)
        self.assertEqual((so["release"], so["build"], so["run_local"]), ("2025 R1", "25.1", "2025-04-29 17:58:01"))
        self.assertEqual((so["nodes"], so["solid_elements"], so["warnings"], so["errors"]), (14009, 2093, 2, 0))
        self.assertAlmostEqual(so["mass_tonne"], 4.1041e-5)
        self.assertEqual(sorted(so["mass_by_type"]), [1, 2])
        self.assertEqual(so["analysis"], "STATIC (STEADY-STATE)")

    def test_parse_mntr(self):
        values, line = ingest.parse_mntr(MNTR)
        self.assertAlmostEqual(values["MxDs"], -0.0068005)
        self.assertEqual(line, 4)

    def test_parse_readme(self):
        r = ingest.parse_readme(README)
        self.assertEqual((r["title"], r["objective"]), ("Title here", "One sentence objective."))
        self.assertEqual([x["thickness"] for x in r["rows"]], [0.85, 1.2])
        self.assertEqual(r["rows"][0]["cols"]["total_deformation"][:2], ("0.00701", "mm"))
        self.assertEqual(r["rows"][0]["cols"]["equivalent_elastic_strain"][1], "1")  # no unit in the header -> dimensionless

    def test_units(self):
        self.assertAlmostEqual(units.convert(2989600, "Pa", "MPa"), 2.9896)
        self.assertAlmostEqual(units.convert(1.25e-9, "tonne mm^-3", "g/cm^3"), 1.25)
        self.assertAlmostEqual(units.convert(2.4, "GPa", "MPa"), 2400)
        self.assertEqual(units.dimension("g/cm³"), "density")
        with self.assertRaises(ValueError):
            units.convert(1.0, "mm", "MPa")  # never guesses across dimensions
        with self.assertRaises(ValueError):
            units.convert(1.0, "furlong", "mm")


if __name__ == "__main__":
    unittest.main()

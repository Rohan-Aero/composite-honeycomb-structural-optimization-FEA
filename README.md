# Composite Honeycomb Sandwich Panel Optimization (FEA)

## Objective
To investigate and optimize the structural performance of composite honeycomb sandwich panels for lightweight aerospace applications using Finite Element Analysis (FEA).

---

## Tools & Software
- ANSYS Workbench
- ANSYS Mechanical
- ANSYS SpaceClaim

---

## Methodology
- Designed hexagonal honeycomb core geometry in ANSYS SpaceClaim  
- Performed static structural analysis in ANSYS Mechanical  
- Conducted parametric study on face sheet thickness (0.85 mm – 1.6 mm)  
- Evaluated deformation, stress distribution, and stiffness characteristics  

---

## Material Configuration

All three cases use the same materials:
- **Core Material:** PLA (Polylactic Acid)
- **Face Sheet Material:** ePA-CF (Carbon Fiber Reinforced)

Only face sheet thickness varies:
| Case | Face Sheet Thickness |
|------|---------------------|
| 1    | 0.85 mm             |
| 2    | 1.2 mm              |
| 3    | 1.6 mm              |

---

## Model Setup

- *Core Material:* PLA  
- *Face Sheets:* Carbon Fiber Reinforced  
- *Boundary Conditions:* Bottom face fully fixed; 1000 N applied as uniform pressure (≈0.144 MPa) over the top face, i.e. a flatwise compression setup  
- *Mesh Strategy:* Quad-dominant solid mesh (SOLID186), 2,093 solid elements / 14,009 nodes, identical for all three cases; no convergence study yet  

---

## Results
- ~21% reduction in **peak** total deformation from 0.85 mm to 1.6 mm (the peak occurs at the unsupported overhanging edge of the top face sheet); average deformation drops only ~2%  
- *1.6 mm* gave the lowest deformation and stress of the three cases tested, at ~29% more mass than 0.85 mm  
- Stiffness-to-weight ratio did not improve significantly: based on peak deformation, 1.2 mm is ~3% better than 0.85 mm and 1.6 mm is ~2% worse  

---

## Detailed Results

| Thickness | Max Deformation (mm) | Avg Deformation (mm) | Von Mises Stress (MPa) | Elastic Strain | Mass (g) |
|-----------|----------------------|----------------------|------------------------|----------------|----------|
| 0.85 mm   | 0.00701              | 0.00214              | 2.9896                 | 0.000896       | 41.0     |
| 1.2 mm    | 0.00601              | 0.00211              | 2.9189                 | 0.000876       | 46.6     |
| 1.6 mm    | 0.00556              | 0.00210              | 2.8536                 | 0.000857       | 53.0     |

**~21% reduction in peak deformation from 0.85mm to 1.6mm (~2% in average deformation)**

---

## Key Insights
- Structural stiffness increases with face sheet thickness  
- Honeycomb geometry provides high strength with low weight  
- Optimization is critical for aerospace structural efficiency  

---

## Future Improvements
- Mesh convergence study  
- Buckling analysis  
- Dynamic loading conditions

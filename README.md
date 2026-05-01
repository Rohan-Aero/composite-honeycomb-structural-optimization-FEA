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
- *Boundary Conditions:* Fixed support + applied load  
- *Mesh Strategy:* Refined mesh for improved accuracy  

---

## Results
- Achieved ~21% reduction in total deformation  
- Identified optimal thickness of *1.6 mm*  
- Improved stiffness-to-weight ratio significantly  

---

## Detailed Results

| Thickness | Deformation (mm) | Von Mises Stress (MPa) | Elastic Strain |
|-----------|-----------------|------------------------|----------------|
| 0.85 mm   | 0.00701         | 2.9896                 | 0.000896       |
| 1.2 mm    | 0.00601         | 2.9189                 | 0.000876       |
| 1.6 mm    | 0.00556         | 2.8536                 | 0.000857       |

**~21% reduction in deformation from 0.85mm to 1.6mm**

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

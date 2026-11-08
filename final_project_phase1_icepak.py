"""
MIE1242 Final Project - Phase 1: Chip Package & Coldplate Model (Slides 10, 14, 15, 16, 17, 19)
Built for Ansys Icepak 2025 R2 Student Version using PyAEDT.

Supports two modeling modes via COLDPLATE_MODE:
  1. "finned_fluid": Full 3D conjugate heat transfer (CHT) coldplate with parameterized
                     fin pitch, fin thickness, fin height, internal liquid cavity,
                     inlet mass/volume flowrate, and pressure outlet (for Phase 1 fin/flow studies).
  2. "htc_plate":    Pure conduction stack with a convective boundary (HTC) on top of the
                     coldplate (matches HW3 workflow for rapid TIM / material sweeps).

Usage:
    python final_project_phase1_icepak.py
"""
import csv
import os
import re
import shutil
import subprocess
import time

try:
    from ansys.aedt.core import Icepak
except ImportError:
    from pyaedt import Icepak

# ----------------------------------------------------------------------------
# 1. AEDT & PROJECT SETTINGS
# ----------------------------------------------------------------------------
AEDT_VERSION = "2025.2"        # Ansys 2025 R2
STUDENT = True                 # Enforces <512k cell student license awareness
KEEP_AEDT_OPEN = True
SOLVE_ON_BUILD = False         # Set True to automatically mesh & run solver after building

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
WORK_DIR = r"C:\Temp\MIE1242_FinalProject_Phase1"
PROJECT_NAME = "MIE1242_Phase1_Coldplate"
DESIGN_NAME = "Phase1_Chip_Coldplate"

# ----------------------------------------------------------------------------
# 2. SLIDE 10, 14, 15, 16, 17, 19 PARAMETERS (PHASE 1)
# ----------------------------------------------------------------------------
# Coldplate Modeling Mode: "finned_fluid" (3D finned liquid coldplate) or "htc_plate" (1D HTC top wall)
COLDPLATE_MODE = "finned_fluid"

# Slide 10 & 17: Silicon Die Power Map (350 W Total = 250 W over 25x25 mm + 100 W over 10x10 mm center)
# Set OVERLAPPING_POWER_MAP = True if 250 W is uniform background across the whole 25x25 mm die
# plus 100 W superimposed in the 10x10 mm center (p_center = 140 W, p_ring = 210 W).
# Set False if 250 W is strictly in the outer ring and 100 W is in the 10x10 mm center.
OVERLAPPING_POWER_MAP = True

# Slide 16: Layer Thicknesses (mm)
T_PCB_MM = 1.2
T_BGA_MM = 0.8
T_SUBSTRATE_MM = 0.8
T_BUMPS_MM = 0.1
T_DIE_MM = 0.7

# Slide 14, 16, 19: Stiffener Ring around the die on top of the substrate
INCLUDE_STIFFENER_RING = True
STIFFENER_WALL_W_MM = 3.0

# Slide 19: TIM (Thermal Interface Material) - "K and thickness TBD"
T_TIM_MM = 0.05                # 50 um baseline (sweep e.g. 0.025, 0.05, 0.10, 0.20 mm)
K_TIM = 5.0                    # 5 W/mK baseline (sweep e.g. 2.0, 5.0, 10.0 W/mK)

# Slide 19 & 43: Coldplate / Heatsink Geometry ("Design fin pitch & thickness", "Fin height")
COLDPLATE_MATERIAL = "Copper"  # "Copper" (400 W/mK) or "Aluminum" (205 W/mK)
CP_XY_MM = 45.0                # Coldplate outer X/Y footprint matching substrate (45 mm x 45 mm)
CP_BASE_THICK_MM = 1.5         # Coldplate bottom baseplate thickness above TIM (mm)
CP_TOP_CAP_MM = 1.5            # Coldplate top cover plate thickness (mm)

FIN_PITCH_MM = 2.0             # Center-to-center fin pitch (mm) -> keep >= 1.5 mm for Student mesh limit
FIN_THICKNESS_MM = 0.8         # Individual fin thickness (mm)
FIN_HEIGHT_MM = 4.0            # Fin height / channel depth (mm)
ACTIVE_FIN_SPAN_X_MM = 27.0    # Width of finned core region centered over the 25x25 mm die (mm)
FIN_LENGTH_Y_MM = 27.0         # Length of fins in flow direction Y (mm)
PLENUM_LENGTH_Y_MM = 5.0       # Inlet/outlet manifold plenum length before/after fins (mm)

# Coolant & Flow Settings (for COLDPLATE_MODE == "finned_fluid")
COOLANT_FLUID = "water"        # "water" (or custom PG25 properties)
FLOW_RATE_LPM = 1.0            # Volumetric flow rate in L/min (1.0 L/min ~= 0.016617 kg/s water)
T_COOLANT_IN_C = 25.0          # Inlet coolant temperature (deg C)
T_AMBIENT_C = 25.0             # Ambient temperature (deg C)

# Equivalent HTC Settings (used only if COLDPLATE_MODE == "htc_plate")
H_TOP_EQUIV = "10000w_per_m2kel"

# Slide 15: Material Thermal Conductivities (W/mK)
K_SILICON = 148.0
K_COPPER = 400.0
K_ALUMINUM = 205.0

# ----------------------------------------------------------------------------
# 3. MESH SETTINGS (SIZED FOR ANSYS STUDENT < 512,000 CELLS)
# ----------------------------------------------------------------------------
MESH_CONFIG = {
    "label": "Student_Safe_Medium",
    "max_xy_mm": 2.0,
    "max_z_mm": 0.4,
    "local_xy_mm": 0.75,
    "thin_cells": 2,
    "min_elems_gap": 2,
}
MIN_GAP_MM = 0.01

# Visual Styling (matching Slide 14, 16, 17, 19 color scheme)
COLORS = {
    "PCB": (84, 130, 53),
    "BGA_balls": (166, 166, 166),
    "Substrate": (112, 173, 71),
    "Bumps": (166, 166, 166),
    "Die_ring": (30, 30, 30),
    "Die_center": (90, 30, 30),
    "Stiffener": (140, 90, 20),
    "TIM": (191, 144, 0),
    "Coldplate_Body": (0, 112, 192),
    "Coolant_Domain": (0, 176, 240),
}
TRANSPARENCY = {
    "Coldplate_Body": 0.55,
    "Coolant_Domain": 0.65,
    "Stiffener": 0.25,
    "Substrate": 0.15,
}

os.makedirs(WORK_DIR, exist_ok=True)
project_path = os.path.join(WORK_DIR, PROJECT_NAME + ".aedt")
results_file = os.path.join(SCRIPT_DIR, "results_phase1_coldplate.csv")


# ----------------------------------------------------------------------------
# HELPER FUNCTIONS
# ----------------------------------------------------------------------------
def cleanup_processes():
    """Terminates lingering Ansys/mesher background processes and resets WORK_DIR."""
    print("Cleaning up any background Ansys processes...")
    for proc in ("ansysedt.exe", "icm.exe", "fluent.exe"):
        subprocess.run(
            ["taskkill", "/F", "/IM", proc, "/T"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    time.sleep(2)
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    os.makedirs(WORK_DIR, exist_ok=True)


def open_icepak(design_name, new_desktop=True):
    """Launches Ansys Icepak 2025 R2 Student."""
    return Icepak(
        project=project_path,
        design=design_name,
        solution_type="SteadyState",
        version=AEDT_VERSION,
        student_version=STUDENT,
        non_graphical=False,
        new_desktop=new_desktop,
    )


def apply_region_settings(region, props):
    """Applies MesherHD dictionary settings compatibility wrapper across PyAEDT versions."""
    try:
        region.manual_settings = True
    except Exception:
        pass
    for key, val in props.items():
        try:
            region.settings[key] = val
        except Exception:
            pass
    try:
        return bool(region.update())
    except Exception:
        return False


def create_materials(ipk, k_tim):
    """Creates isotropic and orthotropic materials per Slide 15."""
    def iso_material(name, k, rho=None, cp=None, mu=None):
        if name.lower() not in ipk.materials.material_keys:
            mat = ipk.materials.add_material(name)
            mat.thermal_conductivity.value = k
            if rho is not None:
                mat.mass_density.value = rho
            if cp is not None:
                mat.specific_heat.value = cp
            if mu is not None:
                mat.viscosity.value = mu

    def aniso_material(name, kxy, kz):
        if name.lower() not in ipk.materials.material_keys:
            mat = ipk.materials.add_material(name)
            mat.thermal_conductivity = [kxy, kxy, kz]

    # Slide 15 Isotropic Materials
    iso_material("mat_Silicon", K_SILICON)
    iso_material("mat_Copper", K_COPPER)
    iso_material("mat_Aluminum", K_ALUMINUM)
    iso_material("mat_TIM", k_tim)

    # Optional 25% Propylene Glycol (PG25) fluid at ~30 C for Slide 35 trade study
    iso_material("mat_PG25", k=0.48, rho=1020.0, cp=3950.0, mu=0.0022)

    # Slide 15 Orthotropic Package Materials
    aniso_material("mat_PCB", 50.0, 1.0)        # PCB: Kx,y = 50 W/mK, Kz = 1 W/mK
    aniso_material("mat_Substrate", 10.0, 1.0)  # Substrate: Kx,y = 10 W/mK, Kz = 1 W/mK
    aniso_material("mat_Bumps", 1.0, 100.0)     # C4 Bumps: Kx,y = 1 W/mK, Kz = 100 W/mK
    aniso_material("mat_BGA", 1.0, 100.0)       # BGA: Kx,y = 1 W/mK, Kz = 100 W/mK


def apply_mesh(ipk, t_tim_mm, mesh_cfg, stack_objs):
    """Configures global and local stack mesh regions beneath the 512k Student cell limit."""
    thinnest_mm = min(T_BUMPS_MM, t_tim_mm)
    size = f"{mesh_cfg['max_xy_mm']}mm"
    max_z = f"{mesh_cfg['max_z_mm']}mm"
    gap = f"{MIN_GAP_MM}mm"
    xy = f"{mesh_cfg['local_xy_mm']}mm"
    local_z_val = thinnest_mm / mesh_cfg["thin_cells"]
    z = f"{local_z_val:.4f}mm"
    min_elems = str(mesh_cfg["min_elems_gap"])

    global_props = {
        "MeshMethod": "MesherHD",
        "UserSpecifiedSettings": True,
        "ComputeGap": False,
        "UniformMeshParametersType": "XYZ Max Sizes",
        "MaxElementSizeX": size,
        "MaxElementSizeY": size,
        "MaxElementSizeZ": max_z,
        "MinGapX": gap,
        "MinGapY": gap,
        "MinGapZ": gap,
        "MinElementsInGap": min_elems,
        "EnableMLM": False,
    }

    glob = ipk.mesh.global_mesh_region
    apply_region_settings(glob, global_props)

    try:
        reg = ipk.mesh.assign_mesh_region(stack_objs, name="refine_stack")
        stack_props = {
            "MeshMethod": "MesherHD",
            "UserSpecifiedSettings": True,
            "ComputeGap": False,
            "UniformMeshParametersType": "XYZ Max Sizes",
            "MaxElementSizeX": xy,
            "MaxElementSizeY": xy,
            "MaxElementSizeZ": z,
            "MinGapX": gap,
            "MinGapY": gap,
            "MinGapZ": gap,
            "MinElementsInGap": min_elems,
            "EnableMLM": False,
        }
        apply_region_settings(reg, stack_props)
    except Exception as err:
        print(f"Warning - local mesh region assignment note: {err}")

    return local_z_val


def build_phase1_model(ipk):
    """Builds the Package (Slides 10, 14-17) and Coldplate (Slide 19) in Ansys Icepak."""
    ipk.modeler.model_units = "mm"

    # Define AEDT design variables for parametric sweeps inside Icepak
    ipk["t_pcb"] = f"{T_PCB_MM}mm"
    ipk["t_bga"] = f"{T_BGA_MM}mm"
    ipk["t_sub"] = f"{T_SUBSTRATE_MM}mm"
    ipk["t_bumps"] = f"{T_BUMPS_MM}mm"
    ipk["t_die"] = f"{T_DIE_MM}mm"
    ipk["t_tim"] = f"{T_TIM_MM}mm"
    ipk["wall_w"] = f"{STIFFENER_WALL_W_MM}mm"

    # Elevations (Z coordinates)
    z_bga = T_PCB_MM
    z_sub = z_bga + T_BGA_MM
    z_bumps = z_sub + T_SUBSTRATE_MM
    z_die = z_bumps + T_BUMPS_MM
    z_tim = z_die + T_DIE_MM
    z_cp_base = z_tim + T_TIM_MM

    create_materials(ipk, K_TIM)

    def box(name, origin, size, material):
        return ipk.modeler.create_box(origin, size, name=name, material=material)

    # ------------------------------------------------------------------------
    # A. PACKAGE STACK (Slides 10, 14, 15, 16, 17)
    # ------------------------------------------------------------------------
    # 1. Printed Circuit Board (PCB): 100 x 100 x 1.2 mm
    box("PCB", ["-50mm", "-50mm", "0mm"], ["100mm", "100mm", "t_pcb"], "mat_PCB")

    # 2. Ball Grid Array (BGA): 45 x 45 x 0.8 mm
    box("BGA_balls", ["-22.5mm", "-22.5mm", f"{z_bga}mm"], ["45mm", "45mm", "t_bga"], "mat_BGA")

    # 3. Substrate: 45 x 45 x 0.8 mm
    box("Substrate", ["-22.5mm", "-22.5mm", f"{z_sub}mm"], ["45mm", "45mm", "t_sub"], "mat_Substrate")

    # 4. C4 Bumps: 25 x 25 x 0.1 mm
    box("Bumps", ["-12.5mm", "-12.5mm", f"{z_bumps}mm"], ["25mm", "25mm", "t_bumps"], "mat_Bumps")

    # 5. Silicon Die (Slide 10): 25 x 25 x 0.7 mm outer ring + 10 x 10 x 0.7 mm center hotspot
    box("Die_ring", ["-12.5mm", "-12.5mm", f"{z_die}mm"], ["25mm", "25mm", "t_die"], "mat_Silicon")
    box("Die_center", ["-5mm", "-5mm", f"{z_die}mm"], ["10mm", "10mm", "t_die"], "mat_Silicon")
    ipk.modeler.subtract(["Die_ring"], ["Die_center"], keep_originals=True)

    # 6. Optional Stiffener Ring shown on Slides 14, 16, 17, 19 (on substrate perimeter)
    if INCLUDE_STIFFENER_RING:
        stiff_h = T_BUMPS_MM + T_DIE_MM
        stiff = box(
            "Stiffener",
            ["-22.5mm", "-22.5mm", f"{z_bumps}mm"],
            ["45mm", "45mm", f"{stiff_h}mm"],
            "mat_Copper",
        )
        stiff_cav = box(
            "Stiffener_cavity",
            ["-22.5mm + wall_w", "-22.5mm + wall_w", f"{z_bumps}mm"],
            ["45mm - 2*wall_w", "45mm - 2*wall_w", f"{stiff_h}mm"],
            "mat_Copper",
        )
        ipk.modeler.subtract([stiff.name], [stiff_cav.name], keep_originals=False)

    # 7. Thermal Interface Material (TIM - Slide 19): 25 x 25 x t_tim mm
    box("TIM", ["-12.5mm", "-12.5mm", f"{z_tim}mm"], ["25mm", "25mm", "t_tim"], "mat_TIM")

    # ------------------------------------------------------------------------
    # B. COLDPLATE / HEATSINK (Slide 19 & Slide 43)
    # ------------------------------------------------------------------------
    cp_mat = "mat_Copper" if COLDPLATE_MATERIAL.lower() == "copper" else "mat_Aluminum"
    stack_refine_objs = ["Bumps", "Die_ring", "Die_center", "TIM"]

    if COLDPLATE_MODE == "finned_fluid":
        # Full 3D Coldplate with Internal Fin Channels & Liquid Flow
        cp_total_h = CP_BASE_THICK_MM + FIN_HEIGHT_MM + CP_TOP_CAP_MM
        z_channel_bot = z_cp_base + CP_BASE_THICK_MM
        z_cp_top = z_cp_base + cp_total_h

        # Outer solid coldplate housing
        box(
            "Coldplate_Body",
            [f"{-CP_XY_MM/2.0}mm", f"{-CP_XY_MM/2.0}mm", f"{z_cp_base}mm"],
            [f"{CP_XY_MM}mm", f"{CP_XY_MM}mm", f"{cp_total_h}mm"],
            cp_mat,
        )

        # Internal fluid cavity (extends from -Y inlet boundary of coldplate to +Y outlet boundary
        # so the inlet/outlet faces sit flush on the coldplate Y-faces for direct boundary assignment)
        cav_w_x = ACTIVE_FIN_SPAN_X_MM
        cav_l_y = CP_XY_MM  # Full Y length so inlet (-Y) and outlet (+Y) are exterior faces

        # Create solid fins inside the core zone [-FIN_LENGTH_Y_MM/2, +FIN_LENGTH_Y_MM/2]
        n_fins = int((cav_w_x - FIN_THICKNESS_MM) // FIN_PITCH_MM) + 1
        total_fin_span = (n_fins - 1) * FIN_PITCH_MM + FIN_THICKNESS_MM
        x_start = -0.5 * total_fin_span

        # Cut the fluid cavity out of Coldplate_Body first, keeping a clone as Coolant_Domain
        cavity_cutter = box(
            "Cavity_Cutter",
            [f"{-cav_w_x/2.0}mm", f"{-cav_l_y/2.0}mm", f"{z_channel_bot}mm"],
            [f"{cav_w_x}mm", f"{cav_l_y}mm", f"{FIN_HEIGHT_MM}mm"],
            cp_mat,
        )
        ipk.modeler.subtract(["Coldplate_Body"], [cavity_cutter.name], keep_originals=False)

        coolant_mat = "water" if COOLANT_FLUID.lower() == "water" else "mat_PG25"
        coolant_obj = box(
            "Coolant_Domain",
            [f"{-cav_w_x/2.0}mm", f"{-cav_l_y/2.0}mm", f"{z_channel_bot}mm"],
            [f"{cav_w_x}mm", f"{cav_l_y}mm", f"{FIN_HEIGHT_MM}mm"],
            coolant_mat,
        )

        # Build the array of solid fins and unite them with Coldplate_Body,
        # while subtracting them from Coolant_Domain so solid & fluid domains are conformal
        fin_names = []
        for i in range(n_fins):
            fx = x_start + i * FIN_PITCH_MM
            f_name = f"Fin_{i+1:02d}"
            box(
                f_name,
                [f"{fx:.4f}mm", f"{-FIN_LENGTH_Y_MM/2.0}mm", f"{z_channel_bot}mm"],
                [f"{FIN_THICKNESS_MM}mm", f"{FIN_LENGTH_Y_MM}mm", f"{FIN_HEIGHT_MM}mm"],
                cp_mat,
            )
            fin_names.append(f_name)

        if fin_names:
            # Subtract fins from Coolant_Domain (keep_originals=True so fins remain as solid parts)
            ipk.modeler.subtract(["Coolant_Domain"], fin_names, keep_originals=True)
            # Unite fins into Coldplate_Body for a single clean solid heatsink body
            ipk.modeler.unite(["Coldplate_Body"] + fin_names)

        print(
            f"Created Finned Coldplate: {n_fins} fins "
            f"(Pitch={FIN_PITCH_MM} mm, Thickness={FIN_THICKNESS_MM} mm, Height={FIN_HEIGHT_MM} mm)"
        )

        # Assign Inlet (-Y face of Coolant_Domain) and Outlet (+Y face of Coolant_Domain)
        # Convert L/min to kg/s (1 L/min water ~ 0.016617 kg/s at 25 C)
        rho_fluid = 997.0 if COOLANT_FLUID.lower() == "water" else 1020.0
        mass_flow_kgs = (FLOW_RATE_LPM / 60000.0) * rho_fluid

        try:
            inlet_face = ipk.modeler["Coolant_Domain"].bottom_face_y
            outlet_face = ipk.modeler["Coolant_Domain"].top_face_y

            ipk.assign_mass_flow_free_opening(
                geometry=[inlet_face.id],
                boundary_name="Coldplate_Inlet",
                mass_flow_rate=f"{mass_flow_kgs:.6f}kg_per_s",
                temperature=f"{T_COOLANT_IN_C}cel",
            )
            ipk.assign_pressure_free_opening(
                geometry=[outlet_face.id],
                boundary_name="Coldplate_Outlet",
                pressure="0n_per_meter_sq",
                temperature=f"{T_COOLANT_IN_C}cel",
            )
        except Exception as err:
            print(f"Note on automatic opening assignment (can also inspect in GUI): {err}")

        # Tight bounding box around the assembly so external air is not meshed unnecessarily
        try:
            ipk.edit_design_settings(ambient_temperature=T_AMBIENT_C)
            ipk.modeler.edit_region_dimensions([0, 0, 0, 0, 0, 0])
        except Exception:
            pass

    else:
        # Simplified 1D Convective Plate Mode (matches HW3 setup)
        box("Coldplate_Body", ["-50mm", "-50mm", f"{z_cp_base}mm"], ["100mm", "100mm", "2mm"], cp_mat)
        try:
            ipk.edit_design_settings(ambient_temperature=T_AMBIENT_C)
            top_face = ipk.modeler["Coldplate_Body"].top_face_z
            ipk.assign_stationary_wall_with_htc(
                geometry=top_face.id,
                name="Coldplate_top_conv",
                htc=H_TOP_EQUIV,
                ref_temperature=f"{T_AMBIENT_C}cel",
            )
            ipk.modeler.edit_region_dimensions([0, 0, 0, 0, 0, 0])
        except Exception:
            pass

    # ------------------------------------------------------------------------
    # C. POWER DISSIPATION (Slides 10 & 17: 350 W Total on Silicon Die)
    # ------------------------------------------------------------------------
    die_area = 25.0 * 25.0
    ctr_area = 10.0 * 10.0
    if OVERLAPPING_POWER_MAP:
        # 250 W uniform over full 25x25 mm die + 100 W additional in 10x10 mm center
        p_ctr = 100.0 + 250.0 * (ctr_area / die_area)             # 140.0 W
        p_ring = 250.0 * ((die_area - ctr_area) / die_area)       # 210.0 W
    else:
        # 250 W in outer ring + 100 W in 10x10 mm center
        p_ctr = 100.0
        p_ring = 250.0

    ipk.assign_source("Die_ring", "Total Power", f"{p_ring}W", boundary_name="Q_ring")
    ipk.assign_source("Die_center", "Total Power", f"{p_ctr}W", boundary_name="Q_center")
    print(f"Assigned Die Power (Slide 10 & 17): Q_center = {p_ctr:.1f} W, Q_ring = {p_ring:.1f} W (Total = 350.0 W)")

    # ------------------------------------------------------------------------
    # D. VISUAL APPEARANCE & SOLVER SETUP
    # ------------------------------------------------------------------------
    for obj_name, rgb in COLORS.items():
        if obj_name in ipk.modeler.object_names:
            try:
                ipk.modeler[obj_name].color = rgb
            except Exception:
                pass
    for obj_name, tr in TRANSPARENCY.items():
        if obj_name in ipk.modeler.object_names:
            try:
                ipk.modeler[obj_name].transparency = tr
            except Exception:
                pass

    setup = ipk.create_setup("Setup1")
    try:
        include_flow = (COLDPLATE_MODE == "finned_fluid")
        setup.props["Include Flow"] = include_flow
        setup.props["Include Gravity"] = False
        setup.props["Max Iterations"] = 250 if include_flow else 200
        setup.props["Convergence Criteria - Energy"] = 1e-7
        if include_flow:
            setup.props["Flow Regime"] = "Laminar" if FLOW_RATE_LPM < 1.5 else "Turbulent"
        setup.update()
    except Exception:
        pass

    local_z_mm = apply_mesh(ipk, T_TIM_MM, MESH_CONFIG, stack_refine_objs)
    ipk.save_project()
    return local_z_mm


def read_results(ipk):
    """Reads peak temperatures on Die_center, Die_ring, and Coldplate_Body."""
    try:
        t_ring = ipk.post.get_scalar_field_value(
            "Temperature", scalar_function="Maximum", object_name="Die_ring", object_type="volume"
        )
        t_center = ipk.post.get_scalar_field_value(
            "Temperature", scalar_function="Maximum", object_name="Die_center", object_type="volume"
        )
        t_cp = ipk.post.get_scalar_field_value(
            "Temperature", scalar_function="Maximum", object_name="Coldplate_Body", object_type="volume"
        )
        try:
            ipk.odesign.GetModule("FieldsReporter").CalcStack("clear")
        except Exception:
            pass
        return float(t_ring), float(t_center), float(t_cp)
    except Exception as err:
        print(f"(Post-processing readout skipped or not solved yet: {err})")
        return None, None, None


# ----------------------------------------------------------------------------
# MAIN EXECUTION
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    cleanup_processes()

    print(f"\n{'='*70}")
    print(f"Building MIE1242 Final Project Phase 1 Model ({COLDPLATE_MODE})")
    print(f"Project Path: {project_path}")
    print(f"{'='*70}")

    ipk = open_icepak(design_name=DESIGN_NAME, new_desktop=True)
    local_z_mm = build_phase1_model(ipk)

    print(f"\nModel built and saved successfully to: {project_path}")
    print(f"  Mode:            {COLDPLATE_MODE}")
    print(f"  TIM1.5:          {T_TIM_MM} mm @ {K_TIM} W/mK")
    print(f"  Coldplate Mat:   {COLDPLATE_MATERIAL}")
    if COLDPLATE_MODE == "finned_fluid":
        print(f"  Fins:            Pitch={FIN_PITCH_MM} mm, Thick={FIN_THICKNESS_MM} mm, Height={FIN_HEIGHT_MM} mm")
        print(f"  Coolant Flow:    {FLOW_RATE_LPM} L/min ({COOLANT_FLUID}) @ {T_COOLANT_IN_C} C")

    if SOLVE_ON_BUILD:
        print("\nRunning Icepak simulation...")
        ipk.analyze_setup("Setup1")
        ipk.save_project()
        t_ring, t_center, t_cp = read_results(ipk)
        if t_center is not None:
            print(f"\nSimulation Results:")
            print(f"  Peak Die Center T: {t_center:.2f} C")
            print(f"  Peak Die Ring T:   {t_ring:.2f} C")
            print(f"  Peak Coldplate T:  {t_cp:.2f} C")
            with open(results_file, "w", newline="") as fh:
                w = csv.writer(fh)
                w.writerow([
                    "mode", "coldplate_mat", "tim_mm", "k_tim",
                    "fin_pitch_mm", "fin_thick_mm", "fin_height_mm", "flow_lpm",
                    "T_die_center_C", "T_die_ring_C", "T_coldplate_C"
                ])
                w.writerow([
                    COLDPLATE_MODE, COLDPLATE_MATERIAL, T_TIM_MM, K_TIM,
                    FIN_PITCH_MM, FIN_THICKNESS_MM, FIN_HEIGHT_MM, FLOW_RATE_LPM,
                    f"{t_center:.3f}", f"{t_ring:.3f}", f"{t_cp:.3f}"
                ])

    if ipk and not KEEP_AEDT_OPEN:
        ipk.release_desktop(close_projects=True, close_desktop=True)

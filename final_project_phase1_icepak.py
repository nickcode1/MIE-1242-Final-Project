"""
MIE1242 Final Project - Phase 1: Chip Package & Coldplate Model
Built for Ansys Icepak 2025 R2 Student Version using PyAEDT 1.9+.

Supports separate parametric sweeps for:
  - "single" (baseline build)
  - "tim_thickness"
  - "fin_pitch"
  - "fin_thickness"
  - "fin_height"
"""
import csv
import os
import shutil
import subprocess
import time

try:
    from ansys.aedt.core import Icepak, settings
except ImportError:
    from pyaedt import Icepak, settings

# Prevent PyAEDT from dropping the gRPC session on non-fatal warnings
settings.release_on_exception = False

# ----------------------------------------------------------------------------
# 1. AEDT & PROJECT SETTINGS
# ----------------------------------------------------------------------------
AEDT_VERSION = "2025.2"
STUDENT = True
KEEP_AEDT_OPEN = True
SOLVE_ON_BUILD = True         # Set True to solve and export CSV automatically

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
WORK_DIR = r"C:\Temp\MIE1242_FinalProject_Phase1"
PROJECT_NAME = "MIE1242_Phase1_Coldplate"
DESIGN_NAME = "Phase1"

# ----------------------------------------------------------------------------
# 2. SWEEP CONFIGURATION
# ----------------------------------------------------------------------------
# Options: "single", "tim_thickness", "fin_pitch", "fin_thickness", "fin_height"
TARGET_SWEEP = "tim_thickness"

SWEEP_RANGES = {
    "tim_thickness": [0.025, 0.05, 0.10, 0.20],
    "fin_pitch": [1.5, 2.0, 2.5, 3.0],
    "fin_thickness": [0.5, 0.8, 1.0, 1.2],
    "fin_height": [3.0, 4.0, 5.0, 6.0],
}

# ----------------------------------------------------------------------------
# 3. BASELINE PARAMETERS (Used when not actively swept)
# ----------------------------------------------------------------------------
COLDPLATE_MODE = "finned_fluid"   # "finned_fluid" or "htc_plate"
OVERLAPPING_POWER_MAP = True

# Slide 16: Layer Thicknesses (mm)
T_PCB_MM = 1.2
T_BGA_MM = 0.8
T_SUBSTRATE_MM = 0.8
T_BUMPS_MM = 0.1
T_DIE_MM = 0.7

# Slide 14, 16, 19: Stiffener Ring
INCLUDE_STIFFENER_RING = True
STIFFENER_WALL_W_MM = 3.0

# Baseline TIM & Coldplate (mm)
BASE_T_TIM = 0.05
K_TIM = 5.0

COLDPLATE_MATERIAL = "Copper"
CP_XY_MM = 45.0
CP_BASE_THICK_MM = 1.5
CP_TOP_CAP_MM = 1.5

BASE_FIN_PITCH = 2.0
BASE_FIN_THICK = 0.8
BASE_FIN_HEIGHT = 4.0
ACTIVE_FIN_SPAN_X_MM = 27.0
FIN_LENGTH_Y_MM = 27.0

# Coolant & Flow Settings
COOLANT_FLUID = "water"
FLOW_RATE_LPM = 1.0
T_COOLANT_IN_C = 25.0
T_AMBIENT_C = 25.0
H_TOP_EQUIV = "10000w_per_m2kel"

# Slide 15: Material Conductivities (W/mK)
K_SILICON = 148.0
K_COPPER = 400.0
K_ALUMINUM = 205.0

# ----------------------------------------------------------------------------
# 4. MESH SETTINGS & VISUALS
# ----------------------------------------------------------------------------
MESH_CONFIG = {
    "label": "Student_Safe_Medium",
    "max_xy_mm": 2.5,
    "max_z_mm": 0.5,
    "local_xy_mm": 1.0,
    "thin_cells": 1,          # 1 hex cell across ultra-thin TIM prevents >512k Student limit crash
    "min_elems_gap": 2,
}
MIN_GAP_MM = 0.02

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
results_file = os.path.join(SCRIPT_DIR, f"results_{TARGET_SWEEP}.csv")

CSV_HEADER = [
    "sweep_mode", "sweep_val", "tim_mm", "fin_pitch_mm",
    "fin_thick_mm", "fin_height_mm", "T_die_center_C",
    "T_die_ring_C", "T_coldplate_C", "p_in_Pa", "p_out_Pa", "dP_Pa",
    "v_in_m_s", "v_out_m_s", "v_max_m_s",
]


# ----------------------------------------------------------------------------
# HELPER FUNCTIONS
# ----------------------------------------------------------------------------
def cleanup_processes():
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
    return Icepak(
        project=project_path,
        design=design_name,
        solution_type="SteadyState",
        version=AEDT_VERSION,
        student_version=STUDENT,
        non_graphical=False,
        new_desktop=new_desktop,
        close_on_exit=False,
    )


def apply_region_settings(region, props, label="region"):
    """Safely updates mesh settings in AEDT 2025.2 without touching read-only 'Command'."""
    try:
        available = set(region.settings.keys())
    except Exception:
        available = None

    for key, val in props.items():
        if key in ("Command", "UserSpecifiedSettings"):
            continue
        if available is not None and key not in available:
            continue
        try:
            region.settings[key] = val
        except Exception:
            pass

    # Enable manual settings via internal dictionary without triggering 'Command is read-only'
    try:
        if hasattr(region, "_settings") and isinstance(region._settings, dict):
            region._settings["UserSpecifiedSettings"] = True
            region._settings.pop("Command", None)
    except Exception:
        pass

    try:
        return bool(region.update())
    except Exception as err:
        print(f"  Mesh note ({label}): region.update() failed: {err}")
        return False


def create_materials(ipk, k_tim):
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

    iso_material("mat_Silicon", K_SILICON)
    iso_material("mat_Copper", K_COPPER)
    iso_material("mat_Aluminum", K_ALUMINUM)
    iso_material("mat_TIM", k_tim)
    iso_material("mat_PG25", k=0.48, rho=1020.0, cp=3950.0, mu=0.0022)
    aniso_material("mat_PCB", 50.0, 1.0)
    aniso_material("mat_Substrate", 10.0, 1.0)
    aniso_material("mat_Bumps", 1.0, 100.0)
    aniso_material("mat_BGA", 1.0, 100.0)


def apply_mesh(ipk, t_tim_mm, mesh_cfg, stack_objs):
    # Keep local Z element size >= 0.025 mm so we stay well within the 512k Student cell limit
    local_z_val = max(min(T_BUMPS_MM, t_tim_mm) / mesh_cfg["thin_cells"], 0.025)
    size = f"{mesh_cfg['max_xy_mm']}mm"
    max_z = f"{mesh_cfg['max_z_mm']}mm"
    gap = f"{MIN_GAP_MM}mm"
    xy = f"{mesh_cfg['local_xy_mm']}mm"
    z = f"{local_z_val:.4f}mm"
    min_elems = str(mesh_cfg["min_elems_gap"])

    glob_props = {
        "MeshMethod": "MesherHD",
        "ComputeGap": True,
        "UniformMeshParametersType": "XYZ Max Sizes",
        "MaxElementSizeX": size,
        "MaxElementSizeY": size,
        "MaxElementSizeZ": max_z,
        "MinGapX": gap,
        "MinGapY": gap,
        "MinGapZ": gap,
        "MinElementsInGap": min_elems,
        "EnableMLM": True,
        "MaxLevels": 2,
        "BufferLayers": 2,
    }
    apply_region_settings(ipk.mesh.global_mesh_region, glob_props, label="global")

    try:
        reg = ipk.mesh.assign_mesh_region(stack_objs, name="refine_stack")
        stack_props = glob_props.copy()
        stack_props.update({
            "MaxElementSizeX": xy,
            "MaxElementSizeY": xy,
            "MaxElementSizeZ": z,
        })
        apply_region_settings(reg, stack_props, label="refine_stack")
    except Exception as err:
        print(f"Warning - local mesh region note: {err}")

    return local_z_val


# ----------------------------------------------------------------------------
# MODEL BUILDER
# ----------------------------------------------------------------------------
def build_phase1_model(ipk, t_tim_mm, fin_pitch_mm, fin_thick_mm, fin_height_mm):
    ipk.modeler.model_units = "mm"

    # Parametric thickness & position variables inside AEDT
    ipk["t_pcb"] = f"{T_PCB_MM}mm"
    ipk["t_bga"] = f"{T_BGA_MM}mm"
    ipk["t_sub"] = f"{T_SUBSTRATE_MM}mm"
    ipk["t_bumps"] = f"{T_BUMPS_MM}mm"
    ipk["t_die"] = f"{T_DIE_MM}mm"
    ipk["t_tim"] = f"{t_tim_mm}mm"
    ipk["wall_w"] = f"{STIFFENER_WALL_W_MM}mm"

    # Parametric Z-elevations linked via AEDT expressions
    ipk["z_bga"] = "t_pcb"
    ipk["z_sub"] = "z_bga + t_bga"
    ipk["z_bumps"] = "z_sub + t_sub"
    ipk["z_die"] = "z_bumps + t_bumps"
    ipk["z_tim"] = "z_die + t_die"
    ipk["z_cp_base"] = "z_tim + t_tim"

    create_materials(ipk, K_TIM)

    def box(name, origin, size, material):
        return ipk.modeler.create_box(origin, size, name=name, material=material)

    # --- A. PACKAGE STACK (Pure Hex Primitives for 100% Orthogonal Mesh Quality) ---
    box("PCB", ["-50mm", "-50mm", "0mm"], ["100mm", "100mm", "t_pcb"], "mat_PCB")
    box("BGA_balls", ["-22.5mm", "-22.5mm", "z_bga"], ["45mm", "45mm", "t_bga"], "mat_BGA")
    box("Substrate", ["-22.5mm", "-22.5mm", "z_sub"], ["45mm", "45mm", "t_sub"], "mat_Substrate")
    box("Bumps", ["-12.5mm", "-12.5mm", "z_bumps"], ["25mm", "25mm", "t_bumps"], "mat_Bumps")

    # Build Die_ring and Die_center as pure hex boxes (resolved via Icepak Object Priority)
    box("Die_ring", ["-12.5mm", "-12.5mm", "z_die"], ["25mm", "25mm", "t_die"], "mat_Silicon")
    box("Die_center", ["-5mm", "-5mm", "z_die"], ["10mm", "10mm", "t_die"], "mat_Silicon")

    stiff_names = []
    if INCLUDE_STIFFENER_RING:
        ipk["stiff_h"] = "t_bumps + t_die"
        # Build Stiffener Ring from 4 pure hex bars so no boolean B-rep subtraction is needed
        box("Stiffener_N", ["-22.5mm", "22.5mm - wall_w", "z_bumps"], ["45mm", "wall_w", "stiff_h"], "mat_Copper")
        box("Stiffener_S", ["-22.5mm", "-22.5mm", "z_bumps"], ["45mm", "wall_w", "stiff_h"], "mat_Copper")
        box("Stiffener_W", ["-22.5mm", "-22.5mm + wall_w", "z_bumps"], ["wall_w", "45mm - 2*wall_w", "stiff_h"], "mat_Copper")
        box("Stiffener_E", ["22.5mm - wall_w", "-22.5mm + wall_w", "z_bumps"], ["wall_w", "45mm - 2*wall_w", "stiff_h"], "mat_Copper")
        stiff_names = ["Stiffener_N", "Stiffener_S", "Stiffener_W", "Stiffener_E"]

    box("TIM", ["-12.5mm", "-12.5mm", "z_tim"], ["25mm", "25mm", "t_tim"], "mat_TIM")

    # --- B. COLDPLATE (Pure Hex Primitives + Priority Hierarchy) ---
    cp_mat = "mat_Copper" if COLDPLATE_MATERIAL.lower() == "copper" else "mat_Aluminum"
    stack_refine_objs = ["Bumps", "Die_ring", "Die_center", "TIM"]
    fin_names = []

    if COLDPLATE_MODE == "finned_fluid":
        ipk["cp_base_thick"] = f"{CP_BASE_THICK_MM}mm"
        ipk["fin_height"] = f"{fin_height_mm}mm"
        ipk["cp_top_cap"] = f"{CP_TOP_CAP_MM}mm"
        ipk["cp_total_h"] = "cp_base_thick + fin_height + cp_top_cap"
        ipk["z_channel_bot"] = "z_cp_base + cp_base_thick"

        box(
            "Coldplate_Body",
            [f"{-CP_XY_MM/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_cp_base"],
            [f"{CP_XY_MM}mm", f"{CP_XY_MM}mm", "cp_total_h"],
            cp_mat,
        )

        cav_w_x = ACTIVE_FIN_SPAN_X_MM
        cav_l_y = CP_XY_MM

        coolant_mat = "water" if COOLANT_FLUID.lower() == "water" else "mat_PG25"
        box(
            "Coolant_Domain",
            [f"{-cav_w_x/2.0}mm", f"{-cav_l_y/2.0}mm", "z_channel_bot"],
            [f"{cav_w_x}mm", f"{cav_l_y}mm", "fin_height"],
            coolant_mat,
        )
        stack_refine_objs.append("Coolant_Domain")

        # Parametric Fin Array (ensure >= 0.6 mm outer channel clearance to prevent sliver cells)
        ipk["fin_pitch"] = f"{fin_pitch_mm}mm"
        ipk["fin_thick"] = f"{fin_thick_mm}mm"
        ipk["fin_len_y"] = f"{FIN_LENGTH_Y_MM}mm"

        n_fins = int((cav_w_x - fin_thick_mm - 1.0) // fin_pitch_mm) + 1
        ipk["x_fin_start"] = f"-0.5 * ({n_fins - 1} * fin_pitch + fin_thick)"

        for i in range(n_fins):
            f_name = f"Fin_{i+1:02d}"
            box(
                f_name,
                [f"x_fin_start + {i}*fin_pitch", "-0.5*fin_len_y", "z_channel_bot"],
                ["fin_thick", "fin_len_y", "fin_height"],
                cp_mat,
            )
            fin_names.append(f_name)

        print(
            f"Created Finned Coldplate: {n_fins} fins "
            f"(Pitch={fin_pitch_mm} mm, Thick={fin_thick_mm} mm, Height={fin_height_mm} mm)"
        )

        # Assign Icepak Object Priorities so nested hex boxes mesh conformally without boolean B-reps!
        # Priority order: lowest first -> highest last
        priority_groups = [
            ["PCB", "BGA_balls", "Substrate", "Bumps", "TIM"] + stiff_names,
            ["Die_ring", "Coldplate_Body"],
            ["Die_center", "Coolant_Domain"],
        ]
        if fin_names:
            priority_groups.append(fin_names)
        ipk.mesh.assign_priorities(priority_groups)

        rho_fluid = 997.0 if COOLANT_FLUID.lower() == "water" else 1020.0
        mass_flow_kgs = (FLOW_RATE_LPM / 60000.0) * rho_fluid

        inlet_face = ipk.modeler["Coolant_Domain"].bottom_face_y
        outlet_face = ipk.modeler["Coolant_Domain"].top_face_y

        # Named face lists for post-processing
        ipk.modeler.create_face_list([inlet_face.id], name="FaceList_Inlet")
        ipk.modeler.create_face_list([outlet_face.id], name="FaceList_Outlet")

        ipk.assign_mass_flow_free_opening(
            [inlet_face.id],
            boundary_name="Coldplate_Inlet",
            mass_flow_rate=f"{mass_flow_kgs:.6f}kg_per_s",
            temperature=f"{T_COOLANT_IN_C}cel",
        )
        ipk.assign_pressure_free_opening(
            [outlet_face.id],
            boundary_name="Coldplate_Outlet",
            pressure="0n_per_meter_sq",
            temperature=f"{T_COOLANT_IN_C}cel",
        )

        ipk.edit_design_settings(ambient_temperature=f"{T_AMBIENT_C}cel")
        # Shrink Y region bounds to match the 45mm coldplate so Inlet/Outlet sit directly on the Region boundary!
        # Padding array: [+X, -X, +Y, -Y, +Z, -Z]
        ipk.modeler.edit_region_dimensions([0, 0, 0, 0, 0, 0])

    else:
        box("Coldplate_Body", ["-50mm", "-50mm", "z_cp_base"], ["100mm", "100mm", "2mm"], cp_mat)
        ipk.mesh.assign_priorities([
            ["PCB", "BGA_balls", "Substrate", "Bumps", "TIM"] + stiff_names,
            ["Die_ring", "Coldplate_Body"],
            ["Die_center"],
        ])
        ipk.edit_design_settings(ambient_temperature=f"{T_AMBIENT_C}cel")
        top_face = ipk.modeler["Coldplate_Body"].top_face_z
        ipk.assign_stationary_wall_with_htc(
            [top_face.id],
            name="Coldplate_top_conv",
            htc=H_TOP_EQUIV,
            ref_temperature=f"{T_AMBIENT_C}cel",
        )
        ipk.modeler.edit_region_dimensions([0, 0, 0, 0, 0, 0])

    # --- C. POWER DISSIPATION ---
    # Because Die_center overrides the center 10x10mm of Die_ring via object priority:
    # Assign volumetric or total power cleanly without overlapping source warnings
    die_area = 25.0 * 25.0
    ctr_area = 10.0 * 10.0
    if OVERLAPPING_POWER_MAP:
        p_ctr = 100.0 + 250.0 * (ctr_area / die_area)        # 140 W in center 10x10
        p_ring = 250.0 * ((die_area - ctr_area) / die_area)  # 210 W in outer ring
    else:
        p_ctr = 100.0
        p_ring = 250.0

    ipk.assign_source("Die_ring", "Total Power", f"{p_ring}W", boundary_name="Q_ring")
    ipk.assign_source("Die_center", "Total Power", f"{p_ctr}W", boundary_name="Q_center")

    # --- D. VISUALS, SETUP & MESH ---
    for obj_name, rgb in COLORS.items():
        if obj_name in ipk.modeler.object_names:
            try:
                ipk.modeler[obj_name].color = rgb
            except Exception:
                pass
    for s_name in stiff_names:
        try:
            ipk.modeler[s_name].color = COLORS["Stiffener"]
            ipk.modeler[s_name].transparency = TRANSPARENCY["Stiffener"]
        except Exception:
            pass
    for f_name in fin_names:
        try:
            ipk.modeler[f_name].color = COLORS["Coldplate_Body"]
        except Exception:
            pass
    for obj_name, tr in TRANSPARENCY.items():
        if obj_name in ipk.modeler.object_names:
            try:
                ipk.modeler[obj_name].transparency = tr
            except Exception:
                pass

    setup = ipk.create_setup("Setup1")
    include_flow = COLDPLATE_MODE == "finned_fluid"
    setup.props["Include Flow"] = include_flow
    setup.props["Include Gravity"] = False
    setup.props["SaveFields"] = True
    setup.props["Max Iterations"] = 250 if include_flow else 200
    setup.props["Convergence Criteria - Energy"] = 1e-7
    if include_flow:
        setup.props["Flow Regime"] = "Laminar" if FLOW_RATE_LPM < 1.5 else "Turbulent"
    setup.update()

    local_z_mm = apply_mesh(ipk, t_tim_mm, MESH_CONFIG, stack_refine_objs)
    return local_z_mm


# ----------------------------------------------------------------------------
# POST-PROCESSING
# ----------------------------------------------------------------------------
def _field(ipk, quantity, obj, func="Maximum", obj_type="volume"):
    """Reads scalar field values using FieldsReporter with automatic quantity-name fallback."""
    omodule = ipk.odesign.GetModule("FieldsReporter")
    
    # Try both standard Icepak field names (e.g., "Temperature" vs "Temp", "Speed" vs "Velocity")
    qty_candidates = [quantity]
    if quantity == "Temperature":
        qty_candidates.append("Temp")
    elif quantity == "Speed":
        qty_candidates.extend(["Velocity", "Mag_Velocity"])

    entered = False
    for q_name in qty_candidates:
        try:
            omodule.CalcStack("clear")
            omodule.EnterQty(q_name)
            entered = True
            break
        except Exception:
            continue

    if not entered:
        # Fallback to PyAEDT wrapper
        val = float(ipk.post.get_scalar_field_value(
            quantity, scalar_function=func, object_name=obj, object_type=obj_type
        ))
        return val - 273.15 if (quantity == "Temperature" and val > 200.0) else val

    if obj_type.lower() == "volume":
        omodule.EnterVol(obj)
    else:
        omodule.EnterSurf(obj)

    if func.lower() in ("mean", "average"):
        try:
            omodule.CalcOp("Mean")
        except Exception:
            omodule.CalcOp("Average")
    else:
        omodule.CalcOp(func)

    tmp_file = os.path.join(WORK_DIR, f"calc_{quantity}_{obj}.out")
    if os.path.exists(tmp_file):
        try:
            os.remove(tmp_file)
        except OSError:
            pass

    variation = []
    for k, v in ipk.available_variations.nominal_w_values_dict.items():
        variation.extend([f"{k}:=", [v]])

    omodule.CalculatorWrite(tmp_file, ["Solution:=", ipk.nominal_sweep], variation)
    omodule.CalcStack("clear")

    with open(tmp_file, "r") as f:
        lines = [line.strip() for line in f if line.strip()]

    raw_val = float(lines[-1].split()[-1])
    if quantity == "Temperature" and raw_val > 200.0:
        return raw_val - 273.15
    return raw_val


def read_results(ipk):
    """Returns a dict of results, or None if the temperature readout fails."""
    try:
        res = {
            "t_ring": _field(ipk, "Temperature", "Die_ring", "Maximum", "volume"),
            "t_center": _field(ipk, "Temperature", "Die_center", "Maximum", "volume"),
            "t_cp": _field(ipk, "Temperature", "Coldplate_Body", "Maximum", "volume"),
            "p_in": None, "p_out": None, "dp_pa": None,
            "v_in": None, "v_out": None, "v_max": None,
        }
    except Exception as err:
        print(f"(Temperature readout error: {err})")
        return None

    if COLDPLATE_MODE == "finned_fluid":
        try:
            res["p_in"] = _field(ipk, "Pressure", "FaceList_Inlet", "Mean", "surface")
            res["p_out"] = _field(ipk, "Pressure", "FaceList_Outlet", "Mean", "surface")
            res["dp_pa"] = res["p_in"] - res["p_out"]
        except Exception as ex:
            print(f"Pressure readout warning: {ex}")
        try:
            res["v_in"] = _field(ipk, "Speed", "FaceList_Inlet", "Mean", "surface")
            res["v_out"] = _field(ipk, "Speed", "FaceList_Outlet", "Mean", "surface")
            res["v_max"] = _field(ipk, "Speed", "Coolant_Domain", "Maximum", "volume")
        except Exception as ex:
            print(f"Velocity readout warning: {ex}")

    return res


def _fmt(val, nd=3):
    return "" if val is None else f"{val:.{nd}f}"


# ----------------------------------------------------------------------------
# MAIN EXECUTION LOOP
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    cleanup_processes()
    print(f"\n{'='*70}")
    print(f"Building MIE1242 Phase 1 Model | Sweep Mode: {TARGET_SWEEP}")
    print(f"{'='*70}")

    runs = []
    if TARGET_SWEEP == "single":
        runs.append({
            "val": "base",
            "t_tim": BASE_T_TIM,
            "pitch": BASE_FIN_PITCH,
            "t_thick": BASE_FIN_THICK,
            "h_fin": BASE_FIN_HEIGHT,
        })
    elif TARGET_SWEEP in SWEEP_RANGES:
        for val in SWEEP_RANGES[TARGET_SWEEP]:
            runs.append({
                "val": val,
                "t_tim": val if TARGET_SWEEP == "tim_thickness" else BASE_T_TIM,
                "pitch": val if TARGET_SWEEP == "fin_pitch" else BASE_FIN_PITCH,
                "t_thick": val if TARGET_SWEEP == "fin_thickness" else BASE_FIN_THICK,
                "h_fin": val if TARGET_SWEEP == "fin_height" else BASE_FIN_HEIGHT,
            })
    else:
        raise ValueError(f"Invalid TARGET_SWEEP: {TARGET_SWEEP}")

    if SOLVE_ON_BUILD:
        with open(results_file, "w", newline="") as fh:
            csv.writer(fh).writerow(CSV_HEADER)

    ipk = None
    for idx, run in enumerate(runs):
        design_case_name = f"{DESIGN_NAME}_{TARGET_SWEEP}_{run['val']}".replace(".", "p")
        print(f"\n--- Generating Design ({idx+1}/{len(runs)}): {design_case_name} ---")

        ipk = open_icepak(design_name=design_case_name, new_desktop=(idx == 0))

        build_phase1_model(ipk, run["t_tim"], run["pitch"], run["t_thick"], run["h_fin"])
        ipk.save_project()

        if SOLVE_ON_BUILD:
            print(f"Solving {design_case_name}...")
            solve_ok = ipk.analyze_setup("Setup1")
            ipk.save_project()
            if not solve_ok:
                print(f"  Solver reported failure for {design_case_name}; check Ansys Message Manager.")
                continue

            res = read_results(ipk)
            if res is None:
                print(f"  No results read for {design_case_name}; skipping CSV row.")
                continue

            print(
                f"  Results -> Die Center T: {res['t_center']:.2f} C | "
                f"Die Ring T: {res['t_ring']:.2f} C | "
                f"Coldplate T: {res['t_cp']:.2f} C | "
                f"dP: {_fmt(res['dp_pa'], 1) or 'n/a'} Pa"
            )
            with open(results_file, "a", newline="") as fh:
                csv.writer(fh).writerow([
                    TARGET_SWEEP, run["val"], run["t_tim"], run["pitch"],
                    run["t_thick"], run["h_fin"],
                    _fmt(res["t_center"]), _fmt(res["t_ring"]), _fmt(res["t_cp"]),
                    _fmt(res["p_in"], 2), _fmt(res["p_out"], 2), _fmt(res["dp_pa"], 2),
                    _fmt(res["v_in"], 4), _fmt(res["v_out"], 4), _fmt(res["v_max"], 4),
                ])

    print(f"\nAll configurations built and saved successfully to: {project_path}")
    if SOLVE_ON_BUILD:
        print(f"Results written to: {results_file}")

    if ipk and not KEEP_AEDT_OPEN:
        ipk.release_desktop(close_projects=True, close_desktop=True)
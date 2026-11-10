"""
MIE1242 Final Project - Phase 1: Chip Package & Coldplate Model
Built for Ansys Icepak 2025 R2 Student Version using PyAEDT 1.9+.
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
TARGET_SWEEP = "tim_thickness"

SWEEP_RANGES = {
    "tim_thickness": [0.025, 0.05, 0.10, 0.20],
    "fin_pitch": [1.5, 2.0, 2.5, 3.0],
    "fin_thickness": [0.5, 0.8, 1.0, 1.2],
    "fin_height": [3.0, 4.0, 5.0, 6.0],
}

# ----------------------------------------------------------------------------
# 3. BASELINE PARAMETERS
# ----------------------------------------------------------------------------
COLDPLATE_MODE = "finned_fluid"
OVERLAPPING_POWER_MAP = True

# Slide 16: Layer Thicknesses (mm)
T_PCB_MM = 1.2
T_BGA_MM = 0.8
T_SUBSTRATE_MM = 0.8
T_BUMPS_MM = 0.1
T_DIE_MM = 0.7
STIFFENER_WALL_W_MM = 3.0

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
FIN_LENGTH_Y_MM = 45.0  # Coldplate covers full 45x45 footprint

COOLANT_FLUID = "water"
FLOW_RATE_LPM = 1.0
T_COOLANT_IN_C = 25.0
T_AMBIENT_C = 25.0
H_TOP_EQUIV = "10000w_per_m2kel"

K_SILICON = 148.0
K_COPPER = 400.0
K_ALUMINUM = 205.0

# ----------------------------------------------------------------------------
# 4. MESH SETTINGS & VISUALS
# ----------------------------------------------------------------------------
MESH_CONFIG = {
    "max_xy_mm": 2.5,
    "max_z_mm": 0.5,
}

COLORS = {
    "PCB": (84, 130, 53),
    "Die_center": (90, 30, 30),
    "Die_ring": (30, 30, 30),
    "Coldplate_Body": (0, 112, 192),
    "Coolant_Domain": (0, 176, 240),
}
TRANSPARENCY = {
    "Coldplate_Body": 0.55,
    "Coolant_Domain": 0.65,
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
        subprocess.run(["taskkill", "/F", "/IM", proc, "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    os.makedirs(WORK_DIR, exist_ok=True)

def open_icepak(design_name, new_desktop=True):
    return Icepak(
        project=project_path, design=design_name, solution_type="SteadyState",
        version=AEDT_VERSION, student_version=STUDENT, non_graphical=False,
        new_desktop=new_desktop, close_on_exit=False,
    )

def create_materials(ipk, k_tim):
    def iso_material(name, k, rho=None, cp=None, mu=None):
        if name.lower() not in ipk.materials.material_keys:
            mat = ipk.materials.add_material(name)
            mat.thermal_conductivity.value = k
            if rho is not None: mat.mass_density.value = rho
            if cp is not None: mat.specific_heat.value = cp
            if mu is not None: mat.viscosity.value = mu

    def aniso_material(name, kxy, kz):
        if name.lower() not in ipk.materials.material_keys:
            mat = ipk.materials.add_material(name)
            mat.thermal_conductivity = [kxy, kxy, kz]

    iso_material("mat_Silicon", K_SILICON)
    iso_material("mat_Copper", K_COPPER)
    iso_material("mat_TIM", k_tim)
    iso_material("mat_PG25", k=0.48, rho=1020.0, cp=3950.0, mu=0.0022)
    aniso_material("mat_PCB", 50.0, 1.0)
    aniso_material("mat_Substrate", 10.0, 1.0)
    aniso_material("mat_Bumps", 1.0, 100.0)
    aniso_material("mat_BGA", 1.0, 100.0)

def apply_mesh_native(ipk, t_tim_mm, mesh_cfg):
    """Safely applies meshing while completely sidestepping PyAEDT's 'Command is read only' bug."""
    try:
        # Global Mesh Settings
        g_reg = ipk.mesh.global_mesh_region
        if "Command" in g_reg.settings:
            del g_reg.settings["Command"]
        g_reg.settings["UserSpecifiedSettings"] = True
        g_reg.settings["MaxElementSizeX"] = f"{mesh_cfg['max_xy_mm']}mm"
        g_reg.settings["MaxElementSizeY"] = f"{mesh_cfg['max_xy_mm']}mm"
        g_reg.settings["MaxElementSizeZ"] = f"{mesh_cfg['max_z_mm']}mm"
        g_reg.settings["EnableMLM"] = True
        g_reg.settings["MaxLevels"] = 2
        g_reg.update()

        # Local Mesh Settings for Stack
        stack = ["TIM", "Die_center", "Die_ring_N", "Die_ring_S", "Die_ring_W", "Die_ring_E", "Coolant_Domain"]
        l_reg = ipk.mesh.assign_mesh_region(stack, name="refine_stack")
        if "Command" in l_reg.settings:
            del l_reg.settings["Command"]
        l_reg.settings["UserSpecifiedSettings"] = True
        l_reg.settings["MaxElementSizeX"] = "1.0mm"
        l_reg.settings["MaxElementSizeY"] = "1.0mm"
        # Bound the Z-size so the student version doesn't exceed 512,000 cells
        l_reg.settings["MaxElementSizeZ"] = f"{max(t_tim_mm, 0.025):.4f}mm"
        l_reg.settings["EnableMLM"] = True
        l_reg.settings["MaxLevels"] = 2
        l_reg.update()
    except Exception as e:
        print(f"Mesh region exception handled safely: {e}")

# ----------------------------------------------------------------------------
# MODEL BUILDER
# ----------------------------------------------------------------------------
def build_phase1_model(ipk, t_tim_mm, fin_pitch_mm, fin_thick_mm, fin_height_mm):
    ipk.modeler.model_units = "mm"

    ipk["t_pcb"] = f"{T_PCB_MM}mm"
    ipk["t_bga"] = f"{T_BGA_MM}mm"
    ipk["t_sub"] = f"{T_SUBSTRATE_MM}mm"
    ipk["t_bumps"] = f"{T_BUMPS_MM}mm"
    ipk["t_die"] = f"{T_DIE_MM}mm"
    ipk["t_tim"] = f"{t_tim_mm}mm"
    ipk["wall_w"] = f"{STIFFENER_WALL_W_MM}mm"

    ipk["z_bga"] = "t_pcb"
    ipk["z_sub"] = "z_bga + t_bga"
    ipk["z_bumps"] = "z_sub + t_sub"
    ipk["z_die"] = "z_bumps + t_bumps"
    ipk["z_tim"] = "z_die + t_die"
    ipk["z_cp_base"] = "z_tim + t_tim"

    create_materials(ipk, K_TIM)

    def box(name, origin, size, material):
        return ipk.modeler.create_box(origin, size, name=name, material=material)

    # By shrinking the PCB to 45x45mm, the global air Region automatically stops at Y = +/-22.5mm.
    # This places the Coolant_Domain openings exactly on the outer boundary, preventing internal boundary crashes!
    box("PCB", ["-22.5mm", "-22.5mm", "0mm"], ["45mm", "45mm", "t_pcb"], "mat_PCB")
    box("BGA_balls", ["-22.5mm", "-22.5mm", "z_bga"], ["45mm", "45mm", "t_bga"], "mat_BGA")
    box("Substrate", ["-22.5mm", "-22.5mm", "z_sub"], ["45mm", "45mm", "t_sub"], "mat_Substrate")
    box("Bumps", ["-12.5mm", "-12.5mm", "z_bumps"], ["25mm", "25mm", "t_bumps"], "mat_Bumps")

    box("Die_center", ["-5mm", "-5mm", "z_die"], ["10mm", "10mm", "t_die"], "mat_Silicon")
    box("Die_ring_N", ["-12.5mm", "5mm", "z_die"], ["25mm", "7.5mm", "t_die"], "mat_Silicon")
    box("Die_ring_S", ["-12.5mm", "-12.5mm", "z_die"], ["25mm", "7.5mm", "t_die"], "mat_Silicon")
    box("Die_ring_W", ["-12.5mm", "-5mm", "z_die"], ["7.5mm", "10mm", "t_die"], "mat_Silicon")
    box("Die_ring_E", ["5mm", "-5mm", "z_die"], ["7.5mm", "10mm", "t_die"], "mat_Silicon")

    ipk["stiff_h"] = "t_bumps + t_die"
    box("Stiffener_N", ["-22.5mm", "22.5mm - wall_w", "z_bumps"], ["45mm", "wall_w", "stiff_h"], "mat_Copper")
    box("Stiffener_S", ["-22.5mm", "-22.5mm", "z_bumps"], ["45mm", "wall_w", "stiff_h"], "mat_Copper")
    box("Stiffener_W", ["-22.5mm", "-22.5mm + wall_w", "z_bumps"], ["wall_w", "45mm - 2*wall_w", "stiff_h"], "mat_Copper")
    box("Stiffener_E", ["22.5mm - wall_w", "-22.5mm + wall_w", "z_bumps"], ["wall_w", "45mm - 2*wall_w", "stiff_h"], "mat_Copper")

    box("TIM", ["-12.5mm", "-12.5mm", "z_tim"], ["25mm", "25mm", "t_tim"], "mat_TIM")

    # --- B. COLDPLATE ---
    cp_mat = "mat_Copper" if COLDPLATE_MATERIAL.lower() == "copper" else "mat_Aluminum"

    ipk["cp_base_thick"] = f"{CP_BASE_THICK_MM}mm"
    ipk["fin_height"] = f"{fin_height_mm}mm"
    ipk["cp_top_cap"] = f"{CP_TOP_CAP_MM}mm"
    ipk["z_channel_bot"] = "z_cp_base + cp_base_thick"
    ipk["z_channel_top"] = "z_channel_bot + fin_height"

    cav_w_x = ACTIVE_FIN_SPAN_X_MM
    wall_x = (CP_XY_MM - cav_w_x) / 2.0 

    box("Coldplate_Body", [f"{-CP_XY_MM/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_cp_base"], [f"{CP_XY_MM}mm", f"{CP_XY_MM}mm", "cp_base_thick"], cp_mat)
    box("Coldplate_Cap", [f"{-CP_XY_MM/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_channel_top"], [f"{CP_XY_MM}mm", f"{CP_XY_MM}mm", "cp_top_cap"], cp_mat)
    box("Coldplate_Wall_W", [f"{-CP_XY_MM/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_channel_bot"], [f"{wall_x}mm", f"{CP_XY_MM}mm", "fin_height"], cp_mat)
    box("Coldplate_Wall_E", [f"{cav_w_x/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_channel_bot"], [f"{wall_x}mm", f"{CP_XY_MM}mm", "fin_height"], cp_mat)

    coolant_mat = "water" if COOLANT_FLUID.lower() == "water" else "mat_PG25"
    box("Coolant_Domain", [f"{-cav_w_x/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_channel_bot"], [f"{cav_w_x}mm", f"{CP_XY_MM}mm", "fin_height"], coolant_mat)

    ipk["fin_pitch"] = f"{fin_pitch_mm}mm"
    ipk["fin_thick"] = f"{fin_thick_mm}mm"
    ipk["fin_len_y"] = f"{CP_XY_MM}mm"

    n_fins = int((cav_w_x - fin_thick_mm - 1.0) // fin_pitch_mm) + 1
    ipk["x_fin_start"] = f"-0.5 * ({n_fins - 1} * fin_pitch + fin_thick)"

    for i in range(n_fins):
        f_name = f"Fin_{i+1:02d}"
        box(f_name, [f"x_fin_start + {i}*fin_pitch", "-0.5*fin_len_y", "z_channel_bot"], ["fin_thick", "fin_len_y", "fin_height"], cp_mat)

    rho_fluid = 997.0 if COOLANT_FLUID.lower() == "water" else 1020.0
    mass_flow_kgs = (FLOW_RATE_LPM / 60000.0) * rho_fluid

    inlet_face = ipk.modeler["Coolant_Domain"].bottom_face_y
    outlet_face = ipk.modeler["Coolant_Domain"].top_face_y

    ipk.modeler.create_face_list([inlet_face.id], name="FaceList_Inlet")
    ipk.modeler.create_face_list([outlet_face.id], name="FaceList_Outlet")

    ipk.assign_mass_flow_free_opening([inlet_face.id], boundary_name="Coldplate_Inlet", mass_flow_rate=f"{mass_flow_kgs:.6f}kg_per_s", temperature=f"{T_COOLANT_IN_C}cel")
    ipk.assign_pressure_free_opening([outlet_face.id], boundary_name="Coldplate_Outlet", pressure="0n_per_meter_sq", temperature=f"{T_COOLANT_IN_C}cel")

    ipk.edit_design_settings(ambient_temperature=f"{T_AMBIENT_C}cel")
    ipk.modeler.edit_region_dimensions([0, 0, 0, 0, 0, 0])

    # --- C. POWER DISSIPATION ---
    die_area = 25.0 * 25.0
    ctr_area = 10.0 * 10.0
    p_ctr = 100.0 + 250.0 * (ctr_area / die_area)
    p_ring = 250.0 * ((die_area - ctr_area) / die_area)

    ring_area = die_area - ctr_area
    p_ring_ns = p_ring * (187.5 / ring_area)
    p_ring_we = p_ring * (75.0 / ring_area)

    ipk.assign_source("Die_ring_N", "Total Power", f"{p_ring_ns:.4f}W", boundary_name="Q_ring_N")
    ipk.assign_source("Die_ring_S", "Total Power", f"{p_ring_ns:.4f}W", boundary_name="Q_ring_S")
    ipk.assign_source("Die_ring_W", "Total Power", f"{p_ring_we:.4f}W", boundary_name="Q_ring_W")
    ipk.assign_source("Die_ring_E", "Total Power", f"{p_ring_we:.4f}W", boundary_name="Q_ring_E")
    ipk.assign_source("Die_center", "Total Power", f"{p_ctr:.4f}W", boundary_name="Q_center")

    setup = ipk.create_setup("Setup1")
    setup.props["Include Flow"] = True
    setup.props["Include Gravity"] = False
    setup.props["SaveFields"] = True
    setup.props["Max Iterations"] = 250
    setup.props["Convergence Criteria - Energy"] = 1e-7
    setup.props["Flow Regime"] = "Laminar" if FLOW_RATE_LPM < 1.5 else "Turbulent"
    setup.update()

    apply_mesh_native(ipk, t_tim_mm, MESH_CONFIG)

# ----------------------------------------------------------------------------
# POST-PROCESSING
# ----------------------------------------------------------------------------
def _field(ipk, quantity, obj, func="Maximum", obj_type="volume"):
    for q_try in ([quantity, "Temp"] if quantity == "Temperature" else [quantity]):
        try:
            val = ipk.post.get_scalar_field_value(q_try, scalar_function=func, object_name=obj, object_type=obj_type)
            if val is not None:
                val = float(val)
                return val - 273.15 if (quantity == "Temperature" and val > 200.0) else val
        except Exception:
            pass

    omodule = ipk.odesign.GetModule("FieldsReporter")
    qty_candidates = [quantity, "Temp"] if quantity == "Temperature" else [quantity, "Velocity", "Mag_Velocity"]

    for q_name in qty_candidates:
        try:
            omodule.CalcStack("clear")
            omodule.EnterQty(q_name)
            break
        except Exception:
            continue

    if obj_type.lower() == "volume": omodule.EnterVol(obj)
    else: omodule.EnterSurf(obj)

    if func.lower() in ("mean", "average"):
        omodule.CalcOp("Integrate")
        if obj_type.lower() == "volume":
            omodule.EnterVol(obj)
            omodule.CalcOp("Volume")
        else:
            omodule.EnterSurf(obj)
            omodule.CalcOp("Area")
        omodule.CalcOp("/")
    else:
        omodule.CalcOp(func)

    tmp_file = os.path.join(WORK_DIR, f"calc_{quantity}_{obj}.out")
    if os.path.exists(tmp_file):
        try: os.remove(tmp_file)
        except OSError: pass

    variation = []
    try:
        for var_name in ipk.variable_manager.independent_variables.keys():
            variation.extend([f"{var_name}:=", ["Nominal"]])
    except Exception:
        pass

    omodule.CalculatorWrite(tmp_file, ["Solution:=", ipk.nominal_sweep], variation)
    omodule.CalcStack("clear")

    with open(tmp_file, "r") as f:
        lines = [line.strip() for line in f if line.strip()]

    raw_val = float(lines[-1].split()[-1])
    return raw_val - 273.15 if (quantity == "Temperature" and raw_val > 200.0) else raw_val

def read_results(ipk):
    try:
        t_ring = max(_field(ipk, "Temperature", r_obj, "Maximum", "volume") for r_obj in ("Die_ring_N", "Die_ring_S", "Die_ring_W", "Die_ring_E"))
        res = {
            "t_ring": t_ring,
            "t_center": _field(ipk, "Temperature", "Die_center", "Maximum", "volume"),
            "t_cp": _field(ipk, "Temperature", "Coldplate_Body", "Maximum", "volume"),
            "p_in": _field(ipk, "Pressure", "FaceList_Inlet", "Mean", "surface"),
            "p_out": _field(ipk, "Pressure", "FaceList_Outlet", "Mean", "surface"),
            "v_in": _field(ipk, "Speed", "FaceList_Inlet", "Mean", "surface"),
            "v_out": _field(ipk, "Speed", "FaceList_Outlet", "Mean", "surface"),
            "v_max": _field(ipk, "Speed", "Coolant_Domain", "Maximum", "volume"),
        }
        res["dp_pa"] = res["p_in"] - res["p_out"]
        return res
    except Exception as err:
        print(f"(Readout error: {err})")
        return None

def _fmt(val, nd=3):
    return "" if val is None else f"{val:.{nd}f}"

# ----------------------------------------------------------------------------
# MAIN EXECUTION LOOP
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    cleanup_processes()
    print(f"\n{'='*70}\nBuilding MIE1242 Phase 1 Model | Sweep Mode: {TARGET_SWEEP}\n{'='*70}")

    runs = []
    for val in SWEEP_RANGES[TARGET_SWEEP]:
        runs.append({
            "val": val, "t_tim": val, "pitch": BASE_FIN_PITCH,
            "t_thick": BASE_FIN_THICK, "h_fin": BASE_FIN_HEIGHT,
        })

    with open(results_file, "w", newline="") as fh:
        csv.writer(fh).writerow(CSV_HEADER)

    ipk = None
    for idx, run in enumerate(runs):
        design_case_name = f"{DESIGN_NAME}_{TARGET_SWEEP}_{run['val']}".replace(".", "p")
        print(f"\n--- Generating Design ({idx+1}/{len(runs)}): {design_case_name} ---")

        ipk = open_icepak(design_name=design_case_name, new_desktop=(idx == 0))
        build_phase1_model(ipk, run["t_tim"], run["pitch"], run["t_thick"], run["h_fin"])
        ipk.save_project()

        print(f"Solving {design_case_name}...")
        if not ipk.analyze_setup("Setup1"):
            print(f"  Solver reported failure for {design_case_name}; check Ansys Message Manager.")
            continue

        res = read_results(ipk)
        if res is None: continue

        print(f"  Results -> Die Center T: {res['t_center']:.2f} C | Die Ring T: {res['t_ring']:.2f} C | dP: {res['dp_pa']:.1f} Pa")
        with open(results_file, "a", newline="") as fh:
            csv.writer(fh).writerow([
                TARGET_SWEEP, run["val"], run["t_tim"], run["pitch"], run["t_thick"], run["h_fin"],
                _fmt(res["t_center"]), _fmt(res["t_ring"]), _fmt(res["t_cp"]),
                _fmt(res["p_in"], 2), _fmt(res["p_out"], 2), _fmt(res["dp_pa"], 2),
                _fmt(res["v_in"], 4), _fmt(res["v_out"], 4), _fmt(res["v_max"], 4),
            ])

    print(f"\nAll configurations built and saved successfully to: {project_path}")
    print(f"Results written to: {results_file}")

    if ipk and not KEEP_AEDT_OPEN:
        ipk.release_desktop(close_projects=True, close_desktop=True)
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

settings.release_on_exception = False

# ----------------------------------------------------------------------------
# 1. AEDT & PROJECT SETTINGS
# ----------------------------------------------------------------------------
AEDT_VERSION = "2025.2"
STUDENT = True
KEEP_AEDT_OPEN = True

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
}

# ----------------------------------------------------------------------------
# 3. BASELINE PARAMETERS
# ----------------------------------------------------------------------------
T_PCB_MM = 1.2
T_BGA_MM = 0.8
T_SUBSTRATE_MM = 0.8
T_BUMPS_MM = 0.1
T_DIE_MM = 0.7
STIFFENER_WALL_W_MM = 3.0

BASE_T_TIM = 0.05
K_TIM = 5.0
K_SILICON = 148.0
K_COPPER = 400.0
K_ALUMINUM = 205.0

CP_XY_MM = 45.0
CP_BASE_THICK_MM = 1.5
CP_TOP_CAP_MM = 1.5

BASE_FIN_PITCH = 2.0
BASE_FIN_THICK = 0.8
BASE_FIN_HEIGHT = 4.0
ACTIVE_FIN_SPAN_X_MM = 27.0
# Leave a 1.0 mm liquid manifold buffer at Y-inlet and Y-outlet so solid fins
# do not overlap the Mass Flow / Pressure Opening boundary faces:
FIN_LENGTH_Y_MM = 43.0

FLOW_RATE_LPM = 1.0
T_COOLANT_IN_C = 25.0
T_AMBIENT_C = 25.0

os.makedirs(WORK_DIR, exist_ok=True)
project_path = os.path.join(WORK_DIR, PROJECT_NAME + ".aedt")
results_file = os.path.join(SCRIPT_DIR, f"results_{TARGET_SWEEP}.csv")

CSV_HEADER = [
    "sweep_mode", "sweep_val", "tim_mm", "fin_pitch_mm",
    "fin_thick_mm", "fin_height_mm", "T_die_max_C",
    "T_coldplate_C", "p_in_Pa", "p_out_Pa", "dP_Pa",
    "v_in_m_s", "v_out_m_s", "v_max_m_s",
]


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


def kill_stranded_solvers():
    """Ensure no hung mesher/solver process locks the project between sweep runs."""
    for proc in ("icm.exe", "fluent.exe"):
        subprocess.run(
            ["taskkill", "/F", "/IM", proc, "/T"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    time.sleep(1)


def create_materials(ipk, k_tim):
    def mat_exists(name):
        return name.lower() in [k.lower() for k in ipk.materials.material_keys]

    def iso_material(name, k, rho=2000.0, cp=700.0):
        if not mat_exists(name):
            mat = ipk.materials.add_material(name)
            mat.thermal_conductivity = k
            mat.mass_density = rho
            mat.specific_heat = cp

    def aniso_material(name, kxy, kz):
        if not mat_exists(name):
            mat = ipk.materials.add_material(name)
            mat.thermal_conductivity = [kxy, kxy, kz]
            mat.mass_density = 1900.0
            mat.specific_heat = 1000.0

    # Use built-in AEDT 'water' (@280K/300K) or 'Water-Liquid' as base so AEDT
    # flags thermal_material_type as Fluid properly.
    if not mat_exists("mat_Water"):
        omaterial_mgr = ipk.oproject.GetDefinitionManager()
        omaterial_mgr.AddMaterial(
            [
                "NAME:mat_Water",
                "CoordinateSystemType:=", "Cartesian",
                "BulkOrSurfaceType:=", 1,
                ["NAME:PhysicsTypes", "set:=", ["Thermal"]],
                "thermal_material_type:=", "Fluid",
                "thermal_conductivity:=", "0.6",
                "mass_density:=", "997",
                "specific_heat:=", "4182",
                "viscosity:=", "0.001",
                "thermal_expansion_coeffcient:=", "0.00021",
            ]
        )
        ipk.materials._load_from_project()

    # Dead-air conduction material for the sealed package cavity around Die/TIM
    iso_material("mat_Air_Dead", 0.026, rho=1.16, cp=1007.0)
    iso_material("mat_Silicon", K_SILICON, rho=2330.0, cp=700.0)
    iso_material("mat_Copper", K_COPPER, rho=8933.0, cp=385.0)
    iso_material("mat_TIM", k_tim, rho=2500.0, cp=800.0)
    aniso_material("mat_PCB", 50.0, 1.0)
    aniso_material("mat_Substrate", 10.0, 1.0)
    aniso_material("mat_Bumps", 1.0, 100.0)
    aniso_material("mat_BGA", 1.0, 100.0)


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

    # Set outer Region to conduction-only dead air so Icepak only solves CFD
    # inside the water Coolant_Domain (avoids unvented dual-fluid crash).
    ipk.modeler["Region"].material_name = "mat_Air_Dead"

    def box(name, origin, size, material):
        return ipk.modeler.create_box(origin, size, name=name, material=material)

    box("PCB", ["-22.5mm", "-22.5mm", "0mm"], ["45mm", "45mm", "t_pcb"], "mat_PCB")
    box("BGA_balls", ["-22.5mm", "-22.5mm", "z_bga"], ["45mm", "45mm", "t_bga"], "mat_BGA")
    box("Substrate", ["-22.5mm", "-22.5mm", "z_sub"], ["45mm", "45mm", "t_sub"], "mat_Substrate")
    box("Bumps", ["-12.5mm", "-12.5mm", "z_bumps"], ["25mm", "25mm", "t_bumps"], "mat_Bumps")
    box("Die", ["-12.5mm", "-12.5mm", "z_die"], ["25mm", "25mm", "t_die"], "mat_Silicon")

    # 2D planar source for the hotspot center
    ipk.modeler.create_rectangle(
        orientation="Z", origin=["-5mm", "-5mm", "z_tim"], sizes=["10mm", "10mm"], name="Die_hotspot"
    )

    ipk["stiff_h"] = "t_bumps + t_die"
    box("Stiffener_N", ["-22.5mm", "22.5mm - wall_w", "z_bumps"], ["45mm", "wall_w", "stiff_h"], "mat_Copper")
    box("Stiffener_S", ["-22.5mm", "-22.5mm", "z_bumps"], ["45mm", "wall_w", "stiff_h"], "mat_Copper")
    box("Stiffener_W", ["-22.5mm", "-22.5mm + wall_w", "z_bumps"], ["wall_w", "45mm - 2*wall_w", "stiff_h"], "mat_Copper")
    box("Stiffener_E", ["22.5mm - wall_w", "-22.5mm + wall_w", "z_bumps"], ["wall_w", "45mm - 2*wall_w", "stiff_h"], "mat_Copper")

    box("TIM", ["-12.5mm", "-12.5mm", "z_tim"], ["25mm", "25mm", "t_tim"], "mat_TIM")

    ipk["cp_base_thick"] = f"{CP_BASE_THICK_MM}mm"
    ipk["fin_height"] = f"{fin_height_mm}mm"
    ipk["cp_top_cap"] = f"{CP_TOP_CAP_MM}mm"
    ipk["z_channel_bot"] = "z_cp_base + cp_base_thick"
    ipk["z_channel_top"] = "z_channel_bot + fin_height"

    cav_w_x = ACTIVE_FIN_SPAN_X_MM
    wall_x = (CP_XY_MM - cav_w_x) / 2.0

    box("Coldplate_Body", [f"{-CP_XY_MM/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_cp_base"], [f"{CP_XY_MM}mm", f"{CP_XY_MM}mm", "cp_base_thick"], "mat_Copper")
    box("Coldplate_Cap", [f"{-CP_XY_MM/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_channel_top"], [f"{CP_XY_MM}mm", f"{CP_XY_MM}mm", "cp_top_cap"], "mat_Copper")
    box("Coldplate_Wall_W", [f"{-CP_XY_MM/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_channel_bot"], [f"{wall_x}mm", f"{CP_XY_MM}mm", "fin_height"], "mat_Copper")
    box("Coldplate_Wall_E", [f"{cav_w_x/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_channel_bot"], [f"{wall_x}mm", f"{CP_XY_MM}mm", "fin_height"], "mat_Copper")

    box("Coolant_Domain", [f"{-cav_w_x/2.0}mm", f"{-CP_XY_MM/2.0}mm", "z_channel_bot"], [f"{cav_w_x}mm", f"{CP_XY_MM}mm", "fin_height"], "mat_Water")

    ipk["fin_pitch"] = f"{fin_pitch_mm}mm"
    ipk["fin_thick"] = f"{fin_thick_mm}mm"
    ipk["fin_len_y"] = f"{FIN_LENGTH_Y_MM}mm"

    n_fins = int((cav_w_x - fin_thick_mm - 1.0) // fin_pitch_mm) + 1
    ipk["x_fin_start"] = f"-0.5 * ({n_fins - 1} * fin_pitch + fin_thick)"

    fin_names = []
    for i in range(n_fins):
        f_name = f"Fin_{i+1:02d}"
        fin_names.append(f_name)
        box(f_name, [f"x_fin_start + {i}*fin_pitch", "-0.5*fin_len_y", "z_channel_bot"], ["fin_thick", "fin_len_y", "fin_height"], "mat_Copper")

    mass_flow_kgs = (FLOW_RATE_LPM / 60000.0) * 997.0
    inlet_face = ipk.modeler["Coolant_Domain"].bottom_face_y
    outlet_face = ipk.modeler["Coolant_Domain"].top_face_y

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
    ipk.modeler.edit_region_dimensions([0, 0, 0, 0, 0, 0])

    # Power Setup
    ipk.assign_source("Die", "Total Power", "210W", boundary_name="Q_Die_Background")
    ipk.assign_source("Die_hotspot", "Total Power", "140W", boundary_name="Q_Die_Center")

    # Solution Setup
    setup = ipk.create_setup("Setup1")
    setup.props["Include Flow"] = True
    setup.props["Include Gravity"] = False
    setup.props["SaveFields"] = True
    setup.props["Max Iterations"] = 250
    setup.props["Convergence Criteria - Energy"] = 1e-7
    setup.props["Flow Regime"] = "Laminar" if FLOW_RATE_LPM < 1.5 else "Turbulent"
    setup.update()

    # Complete Native EditGlobalMeshRegion Call (including mandatory keys and Objects:=["Region"])
    omesh = ipk.odesign.GetModule("MeshRegion")
    omesh.EditGlobalMeshRegion(
        [
            "NAME:Settings",
            "MeshMethod:=", "MesherHD",
            "UserSpecifiedSettings:=", True,
            "ComputeGap:=", True,
            "MaxElementSizeX:=", "2.0mm",
            "MaxElementSizeY:=", "2.0mm",
            "MaxElementSizeZ:=", "0.25mm",
            "MinElementsInGap:=", "3",
            "MinElementsOnEdge:=", "2",
            "MaxSizeRatio:=", "2",
            "NoOGrids:=", False,
            "EnableMLM:=", True,
            "EnforeMLMType:=", "3D",
            "MaxLevels:=", "3",
            "BufferLayers:=", "1",
            "UniformMeshParametersType:=", "XYZ Max Sizes",
            "StairStepMeshing:=", False,
            "MinGapX:=", "0.005mm",
            "MinGapY:=", "0.005mm",
            "MinGapZ:=", "0.005mm",
            "Objects:=", ["Region"],
        ]
    )

    # Local mesh refinement on thin TIM, Die, and Bumps so 0.025mm TIM is always resolved
    omesh.AssignMeshOperation(
        [
            "NAME:Mesh_ThinLayers",
            "Enable:=", True,
            "MaxLevel:=", "3",
            "MinLevel:=", "2",
            "Objects:=", ["TIM", "Die", "Bumps", "Die_hotspot"],
        ]
    )


# ----------------------------------------------------------------------------
# POST-PROCESSING
# ----------------------------------------------------------------------------
def _field(ipk, quantity, obj, func="Maximum", obj_type="volume"):
    for q_try in ([quantity, "Temp"] if quantity == "Temperature" else [quantity]):
        try:
            val = ipk.post.get_scalar_field_value(
                q_try, scalar_function=func, object_name=obj, object_type=obj_type
            )
            if val is not None:
                val = float(val)
                return val - 273.15 if (quantity == "Temperature" and val > 200.0) else val
        except Exception:
            pass
    return None


def read_results(ipk):
    try:
        t_die_max = _field(ipk, "Temperature", "Die", "Maximum", "volume")
        t_cp = _field(ipk, "Temperature", "Coldplate_Body", "Maximum", "volume")
        p_in = _field(ipk, "Pressure", "FaceList_Inlet", "Mean", "surface")
        p_out = _field(ipk, "Pressure", "FaceList_Outlet", "Mean", "surface")
        v_in = _field(ipk, "Speed", "FaceList_Inlet", "Mean", "surface")
        v_out = _field(ipk, "Speed", "FaceList_Outlet", "Mean", "surface")
        v_max = _field(ipk, "Speed", "Coolant_Domain", "Maximum", "volume")
        dp_pa = (p_in - p_out) if (p_in is not None and p_out is not None) else None

        return {
            "t_die_max": t_die_max, "t_cp": t_cp, "p_in": p_in, "p_out": p_out,
            "dp_pa": dp_pa, "v_in": v_in, "v_out": v_out, "v_max": v_max,
        }
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
        runs.append(
            {
                "val": val,
                "t_tim": val,
                "pitch": BASE_FIN_PITCH,
                "t_thick": BASE_FIN_THICK,
                "h_fin": BASE_FIN_HEIGHT,
            }
        )

    with open(results_file, "w", newline="") as fh:
        csv.writer(fh).writerow(CSV_HEADER)

    ipk = None
    for idx, run in enumerate(runs):
        kill_stranded_solvers()
        design_case_name = f"{DESIGN_NAME}_{TARGET_SWEEP}_{run['val']}".replace(".", "p")
        print(f"\n--- Generating Design ({idx+1}/{len(runs)}): {design_case_name} ---")

        if ipk is None:
            ipk = Icepak(
                project=project_path,
                design=design_case_name,
                solution_type="SteadyState",
                version=AEDT_VERSION,
                student_version=STUDENT,
                non_graphical=False,
                new_desktop=True,
                close_on_exit=False,
            )
        else:
            ipk.insert_design(design_case_name)

        build_phase1_model(ipk, run["t_tim"], run["pitch"], run["t_thick"], run["h_fin"])
        ipk.save_project()

        print(f"Solving {design_case_name}...")
        if not ipk.analyze_setup("Setup1"):
            print(f"  Solver reported failure for {design_case_name}; check Ansys Message Manager.")
            continue

        res = read_results(ipk)
        if res is None:
            continue

        print(
            f"  Results -> Die Max T: {_fmt(res['t_die_max'], 2)} C | "
            f"Coldplate T: {_fmt(res['t_cp'], 2)} C | dP: {_fmt(res['dp_pa'], 1)} Pa"
        )
        with open(results_file, "a", newline="") as fh:
            csv.writer(fh).writerow(
                [
                    TARGET_SWEEP, run["val"], run["t_tim"], run["pitch"], run["t_thick"], run["h_fin"],
                    _fmt(res["t_die_max"]), _fmt(res["t_cp"]),
                    _fmt(res["p_in"], 2), _fmt(res["p_out"], 2), _fmt(res["dp_pa"], 2),
                    _fmt(res["v_in"], 4), _fmt(res["v_out"], 4), _fmt(res["v_max"], 4),
                ]
            )

    print(f"\nAll configurations built and saved successfully to: {project_path}")
    print(f"Results written to: {results_file}")

    if ipk and not KEEP_AEDT_OPEN:
        ipk.release_desktop(close_projects=True, close_desktop=True)
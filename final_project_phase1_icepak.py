def read_results(ipk):
    """Extracts peak temperatures, inlet/outlet pressures, pressure drop, and flow velocities."""
    try:
        # Correct PyAEDT 1.9 keyword signature for scalar field evaluation
        t_ring = float(ipk.post.get_scalar_field_value(
            quantity_name="Temperature",
            scalar_function="Maximum",
            specified_domain="object",
            geometry_list=["Die_ring"]
        ))
        t_center = float(ipk.post.get_scalar_field_value(
            quantity_name="Temperature",
            scalar_function="Maximum",
            specified_domain="object",
            geometry_list=["Die_center"]
        ))
        t_cp = float(ipk.post.get_scalar_field_value(
            quantity_name="Temperature",
            scalar_function="Maximum",
            specified_domain="object",
            geometry_list=["Coldplate_Body"]
        ))

        p_in = p_out = dp_pa = v_in = v_out = v_max = 0.0

        if COLDPLATE_MODE == "finned_fluid":
            try:
                p_in = float(ipk.post.get_scalar_field_value(
                    quantity_name="Pressure", scalar_function="Average",
                    specified_domain="facelist", geometry_list=["FaceList_Inlet"]
                ))
                p_out = float(ipk.post.get_scalar_field_value(
                    quantity_name="Pressure", scalar_function="Average",
                    specified_domain="facelist", geometry_list=["FaceList_Outlet"]
                ))
                dp_pa = p_in - p_out

                v_in = float(ipk.post.get_scalar_field_value(
                    quantity_name="Velocity", scalar_function="Average",
                    specified_domain="facelist", geometry_list=["FaceList_Inlet"]
                ))
                v_out = float(ipk.post.get_scalar_field_value(
                    quantity_name="Velocity", scalar_function="Average",
                    specified_domain="facelist", geometry_list=["FaceList_Outlet"]
                ))
                v_max = float(ipk.post.get_scalar_field_value(
                    quantity_name="Velocity", scalar_function="Maximum",
                    specified_domain="object", geometry_list=["Coolant_Domain"]
                ))
            except Exception as ex:
                print(f"Fluid metric extraction warning: {ex}")

        try:
            ipk.odesign.GetModule("FieldsReporter").CalcStack("clear")
        except Exception:
            pass

        return {
            "t_ring": t_ring, "t_center": t_center, "t_cp": t_cp,
            "p_in": p_in, "p_out": p_out, "dp_pa": dp_pa,
            "v_in": v_in, "v_out": v_out, "v_max": v_max
        }
    except Exception as err:
        print(f"(Post-processing readout error: {err})")
        return None
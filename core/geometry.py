import cadquery as cq
import numpy as np

class MorphoRidge:
    """Creates a single ridge (tree-like)"""
    def __init__(self, config):
        """
        Initialize a MorphoRidge object with the given configuration.
        Args:
            config (dict): Configuration dictionary with ridge parameters.
        """
        self.number_of_layers = int(config['number_of_layers'])
        self.chitin_layer_thickness = config['chitin_layer_thickness']
        self.air_layer_thickness = config['air_layer_thickness']
        self.ridge_trunk_width = config.get('ridge_trunk_width', 0)
        self.ridge_total_width = config['ridge_total_width']
        self.structure_thickness_y = config.get('structure_thickness_along_y', 1.0)
        self.branch_arrangement = config.get('branch_arrangement', 'staggered')
        self.inclination_angle_radians = config.get('inclination_angle_radians', 0)
        self.ridge_height = self.number_of_layers * (self.chitin_layer_thickness + self.air_layer_thickness)
        self.branch_width = (self.ridge_total_width - self.ridge_trunk_width) / 2 if self.ridge_total_width > self.ridge_trunk_width else 0
        self.tree_shape = config.get('tree_shape', 'regular')

    def build(self):
        """
        Build the 3D geometry of the ridge according to the configuration.
        Returns:
            cadquery.Workplane: The constructed ridge geometry.
        """
        # if there are no layers do not build anything
        if self.number_of_layers == 0:
            return cq.Workplane("XY")

        # Precompute angle factors if inclined
        if self.inclination_angle_radians != 0:
            cos_angle = np.cos(self.inclination_angle_radians)
            sin_angle = np.sin(self.inclination_angle_radians)
        else:
            cos_angle = 1.0
            sin_angle = 0.0

        ridge = cq.Workplane("XY")
        trunk_layer_height = self.chitin_layer_thickness + self.air_layer_thickness

        # --- Stepped triangular with multilayers and air ---
        if self.tree_shape == 'triangular':
            # --- Continuous pyramidal trunk (progressive narrowing, does not end in a tip) ---
            total_height = self.number_of_layers * (self.chitin_layer_thickness + self.air_layer_thickness)
            trunk_sections = []
            z_pos = 0.0
            min_trunk_frac = 0.3
            for layer_idx in range(self.number_of_layers):
                chitin_thickness = self.chitin_layer_thickness
                air_thickness = self.air_layer_thickness
                frac = layer_idx / self.number_of_layers
                next_frac = (layer_idx + 1) / self.number_of_layers
                # Lower and upper width of the trunk in this segment
                trunk_width_base = self.ridge_trunk_width * (1 - frac * (1 - min_trunk_frac))
                trunk_width_top = self.ridge_trunk_width * (1 - next_frac * (1 - min_trunk_frac))
                # Skip section if both widths are zero or negative
                if trunk_width_base <= 0 and trunk_width_top <= 0:
                    z_pos += chitin_thickness + air_thickness
                    continue
                # --- Trunk section (chitin + air) ---
                section_height = chitin_thickness + air_thickness
                # Create a trapezoidal trunk (extrusion from one rectangle to another)
                if trunk_width_base > 0 and trunk_width_top > 0:
                    trunk_section = (
                        cq.Workplane("XY")
                        .workplane(offset=z_pos)
                        .polyline([
                            (-trunk_width_base / 2, -self.structure_thickness_y / 2),
                            (trunk_width_base / 2, -self.structure_thickness_y / 2),
                            (trunk_width_base / 2, self.structure_thickness_y / 2),
                            (-trunk_width_base / 2, self.structure_thickness_y / 2),
                            (-trunk_width_base / 2, -self.structure_thickness_y / 2),
                        ])
                        .close()
                        .workplane(offset=section_height)
                        .polyline([
                            (-trunk_width_top / 2, -self.structure_thickness_y / 2),
                            (trunk_width_top / 2, -self.structure_thickness_y / 2),
                            (trunk_width_top / 2, self.structure_thickness_y / 2),
                            (-trunk_width_top / 2, self.structure_thickness_y / 2),
                            (-trunk_width_top / 2, -self.structure_thickness_y / 2),
                        ])
                        .close()
                        .loft(combine=True)
                    )
                    trunk_sections.append(trunk_section)
                z_pos += section_height
            # Join all trunk sections
            if trunk_sections:
                trunk = trunk_sections[0]
                for sec in trunk_sections[1:]:
                    trunk = trunk.union(sec)
                ridge = ridge.union(trunk)

            # --- Lateral branches only in chitin layers ---
            z_pos = 0.0
            for layer_idx in range(self.number_of_layers):
                chitin_thickness = self.chitin_layer_thickness
                frac = layer_idx / self.number_of_layers
                next_frac = (layer_idx + 1) / self.number_of_layers
                trunk_width = self.ridge_trunk_width * (1 - frac * (1 - min_trunk_frac))
                total_width = self.ridge_total_width * (1 - frac)
                total_width = max(total_width, trunk_width)
                branch_width = (total_width - trunk_width) / 2
                # --- Lateral branches (chitin) ---
                if branch_width > 0.001 and trunk_width > 0.001:
                    offset = (self.air_layer_thickness + self.chitin_layer_thickness) / 2 if self.branch_arrangement == 'staggered' else 0
                    branch_left = cq.Workplane("XY").box(
                        branch_width,
                        self.structure_thickness_y,
                        chitin_thickness
                    ).translate((-(trunk_width + branch_width)/2, 0, z_pos + chitin_thickness/2))
                    ridge = ridge.union(branch_left)
                    branch_right = cq.Workplane("XY").box(
                        branch_width,
                        self.structure_thickness_y,
                        chitin_thickness
                    ).translate(((trunk_width + branch_width)/2, 0, z_pos + chitin_thickness/2 + offset))
                    ridge = ridge.union(branch_right)
                z_pos += chitin_thickness
                z_pos += self.air_layer_thickness
        else:
            # --- Regular logic ---
            for layer_idx in range(self.number_of_layers):
                z_pos = layer_idx * trunk_layer_height
                z_center = z_pos + trunk_layer_height / 2
                if cos_angle > 0.01:
                    trunk_y_length = (self.structure_thickness_y + z_center * sin_angle) / cos_angle
                else:
                    trunk_y_length = self.structure_thickness_y * 2.0
                # Only create trunk segment if width > 0.001
                if self.ridge_trunk_width > 0.001:
                    trunk_segment = cq.Workplane("XY").box(
                        self.ridge_trunk_width, 
                        trunk_y_length, 
                        trunk_layer_height
                    ).translate((0, 0, z_center))
                    ridge = ridge.union(trunk_segment)
            for i in range(self.number_of_layers):
                z_position = self.chitin_layer_thickness/2 + i * (self.air_layer_thickness + self.chitin_layer_thickness)
                if cos_angle > 0.01:
                    y_length_for_layer = (self.structure_thickness_y + z_position * sin_angle) / cos_angle
                else:
                    y_length_for_layer = self.structure_thickness_y * 2.0
                # Only create branch if width > 0.001
                if self.branch_width > 0.001:
                    branch = cq.Workplane("XY").box(self.branch_width, y_length_for_layer, self.chitin_layer_thickness)
                    ridge = ridge.union(branch.translate((-(self.branch_width + self.ridge_trunk_width)/2, 0, z_position)))
                    offset = (self.air_layer_thickness + self.chitin_layer_thickness) / 2 if self.branch_arrangement == 'staggered' else 0
                    ridge = ridge.union(branch.translate(((self.branch_width + self.ridge_trunk_width)/2, 0, z_position + offset)))
            
        # 3. Inclination and Trimming Logic
        if self.inclination_angle_radians != 0:
            # Rotate the structure on the X axis
            # Convert from radians to degrees for CadQuery
            angle_deg = np.degrees(self.inclination_angle_radians)
            ridge = ridge.rotate((0, 0, 0), (1, 0, 0), angle_deg)
            
            # 4. TRIMMING (Bounding Box)
            # After rotation on X-axis by θ, a point (y, z) maps to:
            # y' = y*cos(θ) - z*sin(θ)
            # z' = y*sin(θ) + z*cos(θ)
            
            cos_angle = np.cos(self.inclination_angle_radians)
            sin_angle = np.sin(self.inclination_angle_radians)
            
            # Original structure extends from:
            # Y: -d/2 to +d/2 (where d = structure_thickness_y)
            # Z: 0 to ridge_height
            d = self.structure_thickness_y
            
            # After rotation, calculate the new bounds in Y and Z
            # Corner points to check: (±d/2, 0), (±d/2, ridge_height)
            y_corners = [
                d/2 * cos_angle - 0 * sin_angle,           # (d/2, 0)
                -d/2 * cos_angle - 0 * sin_angle,          # (-d/2, 0)
                d/2 * cos_angle - self.ridge_height * sin_angle,    # (d/2, ridge_height)
                -d/2 * cos_angle - self.ridge_height * sin_angle    # (-d/2, ridge_height)
            ]
            
            z_corners = [
                d/2 * sin_angle + 0 * cos_angle,           # (d/2, 0)
                -d/2 * sin_angle + 0 * cos_angle,          # (-d/2, 0)
                d/2 * sin_angle + self.ridge_height * cos_angle,    # (d/2, ridge_height)
                -d/2 * sin_angle + self.ridge_height * cos_angle    # (-d/2, ridge_height)
            ]
            
            min_y = min(y_corners)
            max_y = max(y_corners)
            min_z = min(z_corners)
            max_z = max(z_corners)
            
            # Size and center of bounding box
            bbox_width_y = max_y - min_y
            bbox_height_z = max_z - min_z
            bbox_center_y = (min_y + max_y) / 2
            bbox_center_z = (min_z + max_z) / 2
            
            # Create bounding box with calculated dimensions and position
            bounding_box = cq.Workplane("XY").box(
                self.ridge_total_width * 2.0,   # Extra margin in X
                bbox_width_y * 1.2,             # With small safety margin
                bbox_height_z * 1.2              # With small safety margin
            ).translate((0, bbox_center_y, bbox_center_z))
            
            # Intersect the model with the box to trim excess
            ridge = ridge.intersect(bounding_box)
            
        return ridge

class MorphoSubstrate:
    """Creates the chitin base (Substrate)"""
    def __init__(self, config, total_width_x, total_depth_y):
        """
        Initialize a MorphoSubstrate object with the given configuration and dimensions.
        Args:
            config (dict): Configuration dictionary for the substrate.
            total_width_x (float): Total width in X direction.
            total_depth_y (float): Total depth in Y direction.
        """
        self.width_x = total_width_x
        self.depth_y = total_depth_y
        self.substrate_thickness_z = config['substrate_thickness_along_z']
        self.air_gap_below_substrate_z = config['air_gap_below_substrate_along_z']

    def build(self):
        """
        Build the 3D geometry of the substrate.
        Returns:
            cadquery.Workplane: The constructed substrate geometry, or None if thickness is zero.
        """
        if self.substrate_thickness_z == 0:
            return None
        substrate = cq.Workplane("XY").box(self.width_x, self.depth_y, self.substrate_thickness_z)
        # Positioning: centered in X, starts at Y=0, downwards in Z
        return substrate.translate((0, self.depth_y / 2, -self.substrate_thickness_z / 2 - self.air_gap_below_substrate_z))

class MorphoPillars:
    """Creates the support beams (pillars)"""
    def __init__(self, config, total_width_x, total_depth_y):
        """
        Initialize a MorphoPillars object with the given configuration and dimensions.
        Args:
            config (dict): Configuration dictionary for the pillars.
            total_width_x (float): Total width in X direction.
            total_depth_y (float): Total depth in Y direction.
        """
        self.width_x = total_width_x
        self.depth_y = total_depth_y
        self.pillar_thickness_y = config['pillar_thickness_along_y']
        self.air_gap_between_pillars_y = config['air_gap_between_pillars_along_y']
        self.pillar_thickness_z = config['air_gap_below_substrate_along_z']

    def build(self):
        """
        Build the 3D geometry of the support pillars.
        Returns:
            cadquery.Workplane: The constructed pillars geometry.
        """
        base_pillar = cq.Workplane("XY").box(self.width_x, self.pillar_thickness_y, self.pillar_thickness_z) \
                                        .translate((0, self.pillar_thickness_y/2, -self.pillar_thickness_z/2))
        pillars_union = cq.Workplane("XY")
        step_y = self.pillar_thickness_y + self.air_gap_between_pillars_y
        num_pillars = int(self.depth_y / step_y)
        
        for l in range(num_pillars):
            y_position = l * step_y
            if (y_position + self.pillar_thickness_y <= self.depth_y):
                pillars_union = pillars_union.union(base_pillar.translate((0, y_position, 0)))
        return pillars_union

class MorphoStructure:
    """MASTER CLASS: Assembles the entire system"""
    def __init__(self, full_config):
        """
        Initialize a MorphoStructure object with the full configuration.
        Args:
            full_config (dict): Full configuration dictionary for the structure.
        """
        self.config = full_config
        # 1. Global dimension calculations
        number_of_ridges_x = int(full_config['number_of_ridges_along_x'])
        ridge_total_width = full_config['ridge_total_width']
        air_gap_between_ridges_x = full_config['air_gap_between_ridges_along_x']
        self.total_width_x = (number_of_ridges_x - 1) * air_gap_between_ridges_x + number_of_ridges_x * ridge_total_width
        self.total_depth_y = full_config.get('structure_thickness_along_y', 1.0)
        self.period_x = ridge_total_width + air_gap_between_ridges_x
        # 2. Initialize generators with global dimensions
        self.ridge_generator = MorphoRidge(full_config)
        self.substrate_generator = MorphoSubstrate(full_config, self.total_width_x, self.total_depth_y)
        self.pillar_generator = MorphoPillars(full_config, self.total_width_x, self.total_depth_y)

    def build_grating(self):
        """
        Replicate the ridge geometry along the X axis to form a grating.
        Returns:
            cadquery.Workplane: The full grating geometry.
        """
        """Replicates the Ridge along the X axis"""
        single_ridge = self.ridge_generator.build()
        full_grating = cq.Workplane("XY")
        number_of_ridges_x = int(self.config['number_of_ridges_along_x'])
        start_x = - (number_of_ridges_x - 1) * self.period_x / 2
        for i in range(number_of_ridges_x):
            x_position = start_x + i * self.period_x
            # Center the ridge in Y as well (from 0 to total_depth_y)
            full_grating = full_grating.union(single_ridge.translate((x_position, self.total_depth_y/2, 0)))
        return full_grating

    def build_full_system(self):
        """
        Assemble the full system, including ridges, substrate, and optional pillars.
        Returns:
            cadquery.Workplane: The complete assembled structure.
        """
        # Modular assembly
        ridges = self.build_grating()
        substrate = self.substrate_generator.build()
        full_model = ridges
        if substrate is not None:
            full_model = full_model.union(substrate)
        if self.config.get('include_pillars', False):
            pillars = self.pillar_generator.build()
            full_model = full_model.union(pillars)
        return full_model
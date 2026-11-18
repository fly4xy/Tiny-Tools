import bpy
from bpy.props import EnumProperty, BoolProperty, FloatProperty, IntProperty, StringProperty, PointerProperty
from bpy.types import PropertyGroup

# pyright: reportInvalidTypeForm=false

class TinyToolsVertexProps(PropertyGroup):
    vertex_group_search: StringProperty(default="")
    show_only_mirror_groups: BoolProperty(default=True)
    
    vertex_groups_columns: EnumProperty(
        name="Columns",
        description="Number of columns for vertex groups display",
        items=[
            ('1', "1 Column", "Display in 1 column"),
            ('2', "2 Columns", "Display in 2 columns"),
            ('3', "3 Columns", "Display in 3 columns"),
            ('4', "4 Columns", "Display in 4 columns"),
        ],
        default='2'
    )

    vertex_groups_sort: EnumProperty(
        name="Sort",
        description="Sort method for vertex groups",
        items=[
            ('ALPHABETICAL', "A-Z", "Alphabetical order"),
            ('BONE_HIERARCHY', "Bone Hierarchy", "Follow bone hierarchy from armature"),
        ],
        default='ALPHABETICAL'
    )

    # Система симметрии
    mirror_direction: EnumProperty(
        name="Symmetrize Direction",
        items=[
            ('L_TO_R', "L > R", "Symmetrize from left to right"),
            ('R_TO_L', "R > L", "Symmetrize from right to left"),
        ],
        default='L_TO_R'
    )

    mirror_check_topology: BoolProperty(
        name="Check Topology",
        description="Ensure symmetrical vertices are topologically connected",
        default=False
    )
    
    mirror_check_normals: BoolProperty(
        name="Check Normals", 
        description="Ensure symmetrical vertices have similar normals",
        default=True
    )
    
    mirror_normal_threshold: FloatProperty(
        name="Normal Threshold",
        description="Maximum angle difference between normals (degrees)",
        default=45.0,
        min=0.0,
        max=180.0
    )

    mirror_search_radius: FloatProperty(
        name="Search Radius",
        default=0.001,
        min=0.0001,
        max=1,
        precision=4,
        description="Search radius for finding symmetrical vertices"
    )

    edge_length_mult: FloatProperty(
        name="Search Radius Edge Length Multiplier",
        default=3.0,
        min=1.0,
        max=10.0,
        precision=2,
        description="Multiplier for search radius based on average edge length. Using for fill holes"
    )

    mirror_weight_mode: EnumProperty(
        name="Weight Mode",
        items=[
            ('REPLACE_ALL', "Replace All", "Completely replace weights in target group"),
            ('ADD_MISSING', "Add Missing", "Only add missing weights, preserve existing"),
        ],
        default='REPLACE_ALL',
        description="How to apply mirrored weights"
    )

    mirror_method: EnumProperty(
        name="Symmetrize Algorithm",
        items=[
            ('CUSTOM', "Smart Algorithm", "Custom algorithm with full control"),
            ('BLENDER', "Blender Standard", "Use Blender's built-in mirror for maximum speed"),
        ],
        default='CUSTOM',
        description="Method for symmetrizing vertex weights"
    )

    mirror_projection_method: EnumProperty(
        name="Projection Method",
        description="Method for projecting weights between different density areas",
        items=[
            ('DIRECT', "Direct (Symmetrical Mesh)", "Direct vertex-to-vertex copy"),
            ('GRADIENT', "Gradient (Any Mesh)", "Gradient-based transfer for different density meshes"),
            ('INTERPOLATION', "Interpolation (Any Mesh)", "Smooth interpolation for hole filling"),
        ],
        default='DIRECT'
    )

    smooth_direct: BoolProperty(
        name="Smooth After Direct",
        description="Apply smoothing after Direct mirroring",
        default=False
    )

    smooth_gradient: BoolProperty(
        name="Smooth After Gradient", 
        description="Apply smoothing after Gradient mirroring",
        default=False
    )

    smooth_interpolation: BoolProperty(
        name="Smooth After Interpolation",
        description="Apply smoothing after Interpolation mirroring", 
        default=False
    )

    smooth_iterations: IntProperty(
        name="Smooth Iterations",
        description="Number of smoothing iterations", 
        default=2,
        min=1,
        max=10
    )

    smooth_intensity: FloatProperty(
        name="Smooth Intensity",
        description="Smoothing intensity (0.0 - 1.0)",
        default=0.5,
        min=0.0, 
        max=1.0,
        precision=2
    )

    use_topology: BoolProperty(
        name="Use Topology",
        default=False,
        description="Use topology based symmetrizing (Blender standard only)"
    )

    project_weights: BoolProperty(
        name="Project Weights",
        default=False,
        description="Project weights for better accuracy on asymmetrical meshes"
    )

    projection_distance: FloatProperty(
        name="Projection Distance",
        default=0.1,
        min=0.001,
        max=100,
        precision=3,
        description="Maximum distance for weight projection"
    )

    projection_steps: IntProperty(
        name="Projection Steps",
        default=5,
        min=1,
        max=10,
        description="Number of steps for weight projection"
    )

    smooth_after_projection_steps: IntProperty(
        name="Smoothing Steps After Projection",
        default=2,
        min=0,
        max=10,
        description="Number of smoothing iterations after projection"
    )

    # ---------- Перенос весов меш -> меш ----------
    transfer_source: PointerProperty(name="From", type=bpy.types.Object, poll=lambda self, o: o.type == 'MESH',
                                     description="Mesh to take the weights from")
    transfer_target: PointerProperty(name="To", type=bpy.types.Object, poll=lambda self, o: o.type == 'MESH',
                                     description="Mesh that receives the weights")
    transfer_groups: EnumProperty(
        name="Groups",
        items=[('ALL', "All Groups", "Every vertex group of the source"),
               ('ACTIVE', "Active Group", "Only the active vertex group of the source")],
        default='ALL')
    transfer_max_distance: FloatProperty(
        name="Max Distance", default=0.0, min=0.0, precision=4, subtype='DISTANCE',
        description="How far a source surface may be. 0 — automatic (3 average source edges)")
    transfer_check_normals: BoolProperty(
        name="Check Normals", default=False,
        description="Ignore source surfaces facing another way — no weights from the opposite side of thin parts")
    transfer_normal_threshold: FloatProperty(name="Normal Threshold", default=60.0, min=0.0, max=180.0,
                                             description="Max angle between target and source normals (degrees)")
    transfer_weight_mode: EnumProperty(
        name="Weights",
        items=[('REPLACE_ALL', "Replace All", "Replace weights of the transferred groups"),
               ('ADD_MISSING', "Add Missing", "Only fill vertices that have no weight yet")],
        default='REPLACE_ALL')
    transfer_smooth: BoolProperty(name="Smooth After", default=False,
                                  description="Smooth the transferred groups afterwards")

    # ---------- Сглаживание весов ----------
    smooth_groups_mode: EnumProperty(
        name="Groups",
        items=[('ACTIVE', "Active Group", "Smooth only the active vertex group"),
               ('ALL', "All Groups", "Smooth every unlocked vertex group")],
        default='ACTIVE')
    smooth_weights_iterations: IntProperty(name="Iterations", default=2, min=1, max=50)
    smooth_weights_factor: FloatProperty(name="Factor", default=0.5, min=0.0, max=1.0, subtype='FACTOR')

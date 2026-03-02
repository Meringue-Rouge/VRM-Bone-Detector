import bpy
from collections import defaultdict

bl_info = {
    "name": "VRM Bone Group Deleter",
    "blender": (4, 2, 0),
    "category": "3D View",
    "author": "Grok",
    "version": (1, 2, 1),
    "location": "View3D > Sidebar > VRM Bone Group Deleter",
    "description": "Groups entire J_Sec_ physics chains + fixed Show Chain (always uses armature edit mode)",
    "warning": "",
    "doc_url": "",
}


# =============================================================================
# PROPERTY GROUPS
# =============================================================================

class VRM_BoneNameItem(bpy.types.PropertyGroup):
    bone_name: bpy.props.StringProperty(name="Bone")


class VRM_BoneGroup(bpy.types.PropertyGroup):
    group_name: bpy.props.StringProperty(name="Group Name")
    bone_names: bpy.props.CollectionProperty(type=VRM_BoneNameItem)


# =============================================================================
# HELPERS
# =============================================================================

def get_active_armature(context):
    obj = context.active_object
    if obj and obj.type == 'ARMATURE':
        return obj
    # If a mesh is selected, return its armature parent (very common with VRM)
    if obj and obj.type == 'MESH' and obj.parent and obj.parent.type == 'ARMATURE':
        return obj.parent
    for o in bpy.data.objects:
        if o.type == 'ARMATURE':
            return o
    return None


# =============================================================================
# OPERATORS
# =============================================================================

class VRM_OT_Detect_Bone_Groups(bpy.types.Operator):
    bl_idname = "vrm.detect_bone_groups"
    bl_label = "Detect Bone Chains (Hierarchy)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        armature = get_active_armature(context)
        if not armature:
            self.report({'ERROR'}, "No armature found")
            return {'CANCELLED'}

        context.scene.vrm_bone_groups.clear()

        bones = armature.data.bones
        children_map = defaultdict(list)
        for bone in bones:
            if bone.parent:
                children_map[bone.parent.name].append(bone)

        sec_roots = [
            bone for bone in bones
            if bone.name.startswith("J_Sec_")
            and (not bone.parent or not bone.parent.name.startswith("J_Sec_"))
        ]
        sec_roots.sort(key=lambda b: b.name)

        for root in sec_roots:
            chain_bones = []
            def recurse(bone):
                chain_bones.append(bone.name)
                for child in sorted(children_map.get(bone.name, []), key=lambda c: c.name):
                    if child.name.startswith("J_Sec_"):
                        recurse(child)
            recurse(root)

            item = context.scene.vrm_bone_groups.add()
            item.group_name = root.name
            for bname in chain_bones:
                bitem = item.bone_names.add()
                bitem.bone_name = bname

        self.report({'INFO'}, f"Detected {len(context.scene.vrm_bone_groups)} secondary bone chains")
        return {'FINISHED'}


class VRM_OT_Dump_Bone_Hierarchy(bpy.types.Operator):
    bl_idname = "vrm.dump_bone_hierarchy"
    bl_label = "Dump Bone Hierarchy to Console"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        armature = get_active_armature(context)
        if not armature:
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        print("\n" + "="*70)
        print(f"VRM BONE HIERARCHY DUMP – {armature.name}")
        print("="*70)

        bones = armature.data.bones
        children_dict = defaultdict(list)
        root_bones = []

        for bone in bones:
            if bone.parent:
                children_dict[bone.parent.name].append(bone.name)
            else:
                root_bones.append(bone.name)

        def print_tree(bone_name, indent=""):
            print(f"{indent}{bone_name}")
            for child in sorted(children_dict.get(bone_name, [])):
                print_tree(child, indent + "    ")

        for root in sorted(root_bones):
            print_tree(root)

        print("="*70)
        print("END OF HIERARCHY DUMP")
        print("="*70 + "\n")

        self.report({'INFO'}, "Hierarchy dumped to console")
        return {'FINISHED'}


class VRM_OT_Show_Bone_Group(bpy.types.Operator):
    """Fixed: Always forces Armature Edit Mode and selects the bones"""
    bl_idname = "vrm.show_bone_group"
    bl_label = "Show Chain"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: bpy.props.StringProperty()

    def execute(self, context):
        armature = get_active_armature(context)
        if not armature:
            self.report({'ERROR'}, "No armature found")
            return {'CANCELLED'}

        group = next((g for g in context.scene.vrm_bone_groups if g.group_name == self.group_name), None)
        if not group:
            self.report({'ERROR'}, f"Group '{self.group_name}' not found")
            return {'CANCELLED'}

        # === FORCE ARMATURE TO BE ACTIVE ===
        if context.active_object != armature:
            bpy.ops.object.select_all(action='DESELECT')
            armature.select_set(True)
            context.view_layer.objects.active = armature

        # === ENTER ARMATURE EDIT MODE ===
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.armature.select_all(action='DESELECT')

        count = 0
        for bitem in group.bone_names:
            eb = armature.data.edit_bones.get(bitem.bone_name)
            if eb:
                eb.select = eb.select_head = eb.select_tail = True
                count += 1

        # Stay in Edit Mode so you can immediately see and delete the bones
        self.report({'INFO'}, f"✅ Highlighted chain '{self.group_name}' → {count} bones (Armature Edit Mode)")
        return {'FINISHED'}


class VRM_OT_Delete_Bone_Group(bpy.types.Operator):
    bl_idname = "vrm.delete_bone_group"
    bl_label = "Delete Chain"
    bl_options = {'REGISTER', 'UNDO'}

    group_name: bpy.props.StringProperty()

    def execute(self, context):
        armature = get_active_armature(context)
        if not armature:
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        group = next((g for g in context.scene.vrm_bone_groups if g.group_name == self.group_name), None)
        if not group:
            self.report({'ERROR'}, f"Group not found")
            return {'CANCELLED'}

        bones_to_delete = [b.bone_name for b in group.bone_names]

        # VRM SpringBone cleanup
        if hasattr(armature.data, "vrm_addon_extension"):
            sb = armature.data.vrm_addon_extension.spring_bone1
            bones_set = set(bones_to_delete)
            for s_idx in range(len(sb.springs)-1, -1, -1):
                spring = sb.springs[s_idx]
                for j_idx in range(len(spring.joints)-1, -1, -1):
                    joint = spring.joints[j_idx]
                    if hasattr(joint.node, "bone_name") and joint.node.bone_name in bones_set:
                        spring.joints.remove(j_idx)
                if len(spring.joints) == 0:
                    sb.springs.remove(s_idx)

        # Delete bones (leaves-first)
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = armature.data.edit_bones
        to_delete = set(bones_to_delete)
        while to_delete:
            deleted = False
            for name in list(to_delete):
                eb = edit_bones.get(name)
                if not eb: 
                    to_delete.discard(name)
                    continue
                if not any(c.name in to_delete for c in eb.children):
                    edit_bones.remove(eb)
                    to_delete.discard(name)
                    deleted = True
            if not deleted:
                break

        # Remove vertex groups
        for child in armature.children:
            if child.type == 'MESH':
                for name in bones_to_delete:
                    vg = child.vertex_groups.get(name)
                    if vg:
                        child.vertex_groups.remove(vg)

        # Remove from UI
        for i in range(len(context.scene.vrm_bone_groups)-1, -1, -1):
            if context.scene.vrm_bone_groups[i].group_name == self.group_name:
                context.scene.vrm_bone_groups.remove(i)
                break

        bpy.ops.object.mode_set(mode='OBJECT')
        self.report({'INFO'}, f"Deleted chain '{self.group_name}' + cleaned springs & vertex groups")
        return {'FINISHED'}


# =============================================================================
# PANEL
# =============================================================================

class VRM_PT_Bone_Group_Deleter(bpy.types.Panel):
    bl_label = "VRM Bone Group Deleter"
    bl_idname = "VRM_PT_Bone_Group_Deleter"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "VRM Bone Group Deleter"

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.operator("vrm.detect_bone_groups", icon='BONE_DATA', text="Detect Bone Chains")
        row.operator("vrm.dump_bone_hierarchy", icon='CONSOLE', text="Dump Hierarchy")

        if not context.scene.vrm_bone_groups:
            return

        box = layout.box()
        box.label(text=f"Detected Chains: {len(context.scene.vrm_bone_groups)}", icon='GROUP_BONE')

        for group in context.scene.vrm_bone_groups:
            row = box.row(align=True)
            row.label(text=group.group_name, icon='CURVE_PATH')
            row.label(text=f"({len(group.bone_names)})")

            op = row.operator("vrm.show_bone_group", text="", icon='HIDE_OFF')
            op.group_name = group.group_name

            op = row.operator("vrm.delete_bone_group", text="", icon='TRASH')
            op.group_name = group.group_name


# =============================================================================
# REGISTER
# =============================================================================

def register():
    bpy.utils.register_class(VRM_BoneNameItem)
    bpy.utils.register_class(VRM_BoneGroup)

    bpy.utils.register_class(VRM_OT_Detect_Bone_Groups)
    bpy.utils.register_class(VRM_OT_Dump_Bone_Hierarchy)
    bpy.utils.register_class(VRM_OT_Show_Bone_Group)
    bpy.utils.register_class(VRM_OT_Delete_Bone_Group)

    bpy.utils.register_class(VRM_PT_Bone_Group_Deleter)

    bpy.types.Scene.vrm_bone_groups = bpy.props.CollectionProperty(type=VRM_BoneGroup)


def unregister():
    bpy.utils.unregister_class(VRM_PT_Bone_Group_Deleter)
    bpy.utils.unregister_class(VRM_OT_Delete_Bone_Group)
    bpy.utils.unregister_class(VRM_OT_Show_Bone_Group)
    bpy.utils.unregister_class(VRM_OT_Dump_Bone_Hierarchy)
    bpy.utils.unregister_class(VRM_OT_Detect_Bone_Groups)

    bpy.utils.unregister_class(VRM_BoneGroup)
    bpy.utils.unregister_class(VRM_BoneNameItem)

    del bpy.types.Scene.vrm_bone_groups


if __name__ == "__main__":
    register()
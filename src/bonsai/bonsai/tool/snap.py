# Bonsai - OpenBIM Blender Add-on
# Copyright (C) 2022 Cyril Waechter <cyril@biminsight.ch>
#
# This file is part of Bonsai.
#
# Bonsai is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Bonsai is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Bonsai.  If not, see <http://www.gnu.org/licenses/>.

import bpy
import ifcopenshell
import bonsai.core.tool
import bonsai.tool as tool
from bonsai.bim.module.model.decorator import PolylineDecorator
import math
import mathutils
from mathutils import Matrix, Vector
from lark import Lark, Transformer
from typing import Union


class Snap(bonsai.core.tool.Snap):
    tool_state = None
    snap_plane_method = None

    @classmethod
    def set_snap_plane_method(cls, value=True):
        cls.snap_plane_method = value

    @classmethod
    def cycle_snap_plane_method(cls, value=True):
        if cls.snap_plane_method == value:
            cls.snap_plane_method = None
            return
        cls.snap_plane_method = value

    @classmethod
    def get_increment_snap_value(cls, context):
        rv3d = context.region_data

        factor = 1
        fractions = [100, 20, 10, 2]
        ortho_threshold = [-0.5, -0.25, -0.15, -0.05]
        distances = [3, 5, 15, 30]

        unit_system = tool.Drawing.get_unit_system()
        unit_scale = ifcopenshell.util.unit.calculate_unit_scale(tool.Ifc.get())
        if unit_system == "IMPERIAL":
            factor = unit_scale
            fractions = [24, 12, 6, 2]
            ortho_threshold = [-10.0, -4.75, -2.2, -0.75]
            distances = [3, 6, 10, 20]

        increment = None
        if rv3d.view_perspective == "PERSP":
            if rv3d.view_distance < distances[0]:
                increment = (1 / fractions[0]) * factor
            elif distances[0] < rv3d.view_distance < distances[1]:
                increment = (1 / fractions[1]) * factor
            elif distances[1] < rv3d.view_distance < distances[2]:
                increment = (1 / fractions[2]) * factor
            elif distances[2] < rv3d.view_distance < distances[3]:
                increment = (1 / fractions[3]) * factor
            else:
                increment = 1 * factor
        if rv3d.view_perspective == "ORTHO" or (
            rv3d.view_perspective == "CAMERA" and context.scene.camera.data.type == "ORTHO"
        ):
            window_scale = rv3d.window_matrix.to_scale()
            if window_scale[1] < ortho_threshold[0]:
                increment = (1 / fractions[0]) * factor
            elif ortho_threshold[0] < window_scale[1] < ortho_threshold[1]:
                increment = (1 / fractions[1]) * factor
            elif ortho_threshold[1] < window_scale[1] < ortho_threshold[2]:
                increment = (1 / fractions[2]) * factor
            elif ortho_threshold[2] < window_scale[1] < ortho_threshold[3]:
                increment = (1 / fractions[3]) * factor
            else:
                increment = 1 * factor

        return increment

    @classmethod
    def get_snap_points_on_raycasted_face(cls, context, event, obj, face_index):
        matrix = obj.matrix_world.copy()
        face = obj.data.polygons[face_index]
        verts = []
        for i in face.vertices:
            verts.append(matrix @ obj.data.vertices[i].co)

        hit, hit_type = tool.Raycast.ray_cast_by_proximity(context, event, obj, face)
        snap_point = (hit, hit_type)
        if hit is None:
            return (None, None)

        return snap_point

    @classmethod
    def update_snapping_point(cls, snap_point, snap_type, snap_obj=None):
        try:
            snap_vertex = bpy.context.scene.BIMPolylineProperties.snap_mouse_point[0]
        except:
            snap_vertex = bpy.context.scene.BIMPolylineProperties.snap_mouse_point.add()

        snap_vertex.x = snap_point[0]
        snap_vertex.y = snap_point[1]
        snap_vertex.z = snap_point[2]
        snap_vertex.snap_type = snap_type
        if snap_obj:
            snap_vertex.snap_object = snap_obj.name
        else:
            snap_vertex.snap_object = ""

    @classmethod
    def clear_snapping_point(cls):
        bpy.context.scene.BIMPolylineProperties.snap_mouse_point.clear()

    @classmethod
    def update_snapping_ref(cls, snap_point, snap_type):
        try:
            snap_vertex = bpy.context.scene.BIMPolylineProperties.snap_mouse_ref[0]
        except:
            snap_vertex = bpy.context.scene.BIMPolylineProperties.snap_mouse_ref.add()

        snap_vertex.x = snap_point[0]
        snap_vertex.y = snap_point[1]
        snap_vertex.z = snap_point[2]
        snap_vertex.snap_type = snap_type

    @classmethod
    def clear_snapping_ref(cls):
        bpy.context.scene.BIMPolylineProperties.snap_mouse_ref.clear()

    @classmethod
    def snap_on_axis(cls, intersection, tool_state):
        def create_axis_line_data(rot_mat, origin):
            length = 1000
            direction = Vector((1, 0, 0))
            if tool_state.plane_method == "YZ" or (not tool_state.plane_method and tool_state.axis_method == "Z"):
                direction = Vector((0, 0, 1))
            rot_dir = rot_mat.inverted() @ direction
            start = origin + rot_dir * length
            end = origin - rot_dir * length

            return start, end

        # Makes the snapping point more or less sticky than others
        # It changes the distance and affects how the snapping point is sorted
        stick_factor = 0.15

        default_container_elevation = tool.Ifc.get_object(tool.Root.get_default_container()).location.z
        polyline_data = bpy.context.scene.BIMPolylineProperties.insertion_polyline
        polyline_points = polyline_data[0].polyline_points if polyline_data else []
        if polyline_points:
            last_point_data = polyline_points[-1]
            last_point = Vector((last_point_data.x, last_point_data.y, last_point_data.z))
        else:
            last_point = Vector((0, 0, default_container_elevation))

        # Translates intersection point based on last_point
        translated_intersection = intersection - last_point
        snap_axis = []
        if not tool_state.lock_axis:
            for i in range(1, 13):
                angle = 30 * i
                snap_axis.append(angle)
        else:
            snap_axis = [tool_state.snap_angle]

        pivot_axis = "Z"
        if tool_state.plane_method == "XZ":
            pivot_axis = "Y"
        if tool_state.plane_method == "YZ":
            pivot_axis = "X"

        # Get axis that are closer than the stick factor threshold
        elegible_axis = []

        for axis in snap_axis:
            if not axis:
                continue
            rot_mat = Matrix.Rotation(math.radians(360 - axis), 3, pivot_axis)
            rot_mat = tool.Polyline.use_transform_orientations(rot_mat)
            rot_intersection = rot_mat @ translated_intersection
            proximity = rot_intersection.y
            if tool_state.plane_method == "XZ":
                proximity = rot_intersection.x

            is_on_rot_axis = abs(proximity) <= stick_factor
            if is_on_rot_axis:
                elegible_axis.append((abs(proximity), axis))

        # Get the eligible axis with the lowest proximity
        if elegible_axis:
            proximity, axis = sorted(elegible_axis)[0]
        else:
            pass

        # If lock axis is on it will use the snap angle so there is no need to search for eligible axis
        if elegible_axis or tool_state.lock_axis:
            # Adapt axis to make snap angle work with other plane method
            if elegible_axis:
                if tool_state.plane_method == "XZ":
                    axis = 90 - (axis * -1)
            else:
                if tool_state.plane_method == "XZ":
                    axis = -axis
                if tool_state.plane_method == "YZ":
                    axis = 90 - (axis * -1)
            rot_mat = Matrix.Rotation(math.radians(360 - axis), 3, pivot_axis)
            rot_mat = tool.Polyline.use_transform_orientations(rot_mat)
            rot_intersection = rot_mat @ translated_intersection
            start, end = create_axis_line_data(rot_mat, last_point)
            PolylineDecorator.set_angle_axis_line(start, end)

            # Snap to axis
            rot_intersection = Vector((rot_intersection.x, 0, rot_intersection.z))
            if tool_state.plane_method == "XZ":
                rot_intersection = Vector((rot_intersection.x, rot_intersection.y, 0))
            # Convert it back
            snap_intersection = rot_mat.inverted() @ rot_intersection + last_point
            return snap_intersection, axis, start, end

        return None, None, None, None

    @classmethod
    def mix_snap_and_axis(cls, snap_point, axis_start, axis_end):
        # Creates a mixed snap point between the locked axis and the object snap
        # Then it sorts them to get the shortest first
        x_axis = tool.Polyline.use_transform_orientations(Vector((1, 0, 0)))
        y_axis = tool.Polyline.use_transform_orientations(Vector((0, 1, 0)))
        z_axis = tool.Polyline.use_transform_orientations(Vector((0, 0, 1)))
        intersections = []
        intersections.append(tool.Cad.intersect_edge_plane(axis_start, axis_end, snap_point, x_axis))
        intersections.append(tool.Cad.intersect_edge_plane(axis_start, axis_end, snap_point, y_axis))
        intersections.append(tool.Cad.intersect_edge_plane(axis_start, axis_end, snap_point, z_axis))

        polyline_data = bpy.context.scene.BIMPolylineProperties.insertion_polyline
        polyline_points = polyline_data[0].polyline_points if polyline_data else []
        if polyline_points:
            last_point_data = polyline_points[-1]
            last_point = Vector((last_point_data.x, last_point_data.y, last_point_data.z))
        else:
            last_point = Vector(0, 0, 0)

        valid_intersections = []
        for i in intersections:
            if i is not None:
                distance = (i - last_point).length
                if not math.isclose(distance, 0.0, abs_tol=1e-4):
                    valid_intersections.append(i)

        sorted_intersections = sorted(valid_intersections, key=lambda x: (x - last_point).length, reverse=True)
        return sorted_intersections

    @classmethod
    def detect_snapping_points(cls, context: bpy.types.Context, event: bpy.types.Event, objs_2d_bbox, tool_state):
        rv3d = context.region_data
        space = context.space_data
        mouse_pos = event.mouse_region_x, event.mouse_region_y
        detected_snaps = []

        snap_threshold = 0.3
        offset = 10
        mouse_offset = (
            (-offset, offset),
            (0, offset),
            (offset, offset),
            (-offset, 0),
            (0, 0),
            (offset, 0),
            (-offset, -offset),
            (0, -offset),
            (offset, -offset),
        )

        def select_plane_method():
            if not last_polyline_point:
                plane_origin = Vector((0, 0, 0))
                plane_normal = Vector((0, 0, 1))
            if not tool_state.plane_method:
                view_rotation = rv3d.view_rotation
                view_location = rv3d.view_location
                view_direction = Vector((0, 0, -1)) @ view_rotation.to_matrix().transposed()
                plane_origin = view_location + view_direction * 10
                plane_normal = view_direction.normalized()

            if tool_state.plane_method == "XY" or (
                not tool_state.plane_method and tool_state.axis_method in {"X", "Y"}
            ):
                if tool_state.use_default_container:
                    plane_origin = Vector((0, 0, elevation))
                elif not last_polyline_point:
                    plane_origin = Vector((0, 0, 0))
                else:
                    plane_origin = Vector((last_polyline_point.x, last_polyline_point.y, last_polyline_point.z))
                plane_normal = Vector((0, 0, 1))

            elif tool_state.plane_method == "XZ" or (not tool_state.plane_method and tool_state.axis_method == "Z"):
                if last_polyline_point:
                    plane_origin = Vector((last_polyline_point.x, last_polyline_point.y, last_polyline_point.z))
                plane_normal = Vector((0, 1, 0))

            elif tool_state.plane_method == "YZ":
                if last_polyline_point:
                    plane_origin = Vector((last_polyline_point.x, last_polyline_point.y, last_polyline_point.z))
                plane_normal = Vector((1, 0, 0))

            plane_normal = tool.Polyline.use_transform_orientations(plane_normal)
            return plane_origin, plane_normal

        def cast_rays_to_single_object(
            obj: bpy.types.Object, mouse_pos: tuple[int, int]
        ) -> Union[tuple[bpy.types.Object, Vector, int], tuple[None, None, None]]:
            if obj.type != "MESH":
                return None, None, None
            hit, normal, face_index = tool.Raycast.obj_ray_cast(context, event, obj)
            if hit is None:
                # Tried original mouse position. Now it will try the offsets.
                original_mouse_pos = mouse_pos
                for value in mouse_offset:
                    mouse_pos = tuple(x + y for x, y in zip(original_mouse_pos, value))
                    hit, normal, face_index = tool.Raycast.obj_ray_cast(context, event, obj, mouse_pos)
                    if hit:
                        break
                mouse_pos = original_mouse_pos
            if hit:
                hit_world = obj.original.matrix_world @ hit
                return obj, hit_world, face_index
            else:
                return None, None, None

        def cast_rays_and_get_best_object(
            objs_to_raycast: list[bpy.types.Object], mouse_pos: tuple[int, int]
        ) -> Union[tuple[bpy.types.Object, Vector, int], tuple[None, None, None]]:
            best_length_squared = 1.0
            best_obj = None
            best_hit = None
            best_face_index = None

            for obj in objs_to_raycast:
                snap_obj, hit, face_index = cast_rays_to_single_object(obj, mouse_pos)

                if hit is not None:
                    length_squared = (hit - ray_origin).length_squared
                    if best_obj is None or length_squared < best_length_squared:
                        best_length_squared = length_squared
                        best_obj = snap_obj
                        best_hit = hit
                        best_face_index = face_index

            if best_obj is not None:
                return best_obj, best_hit, best_face_index

            else:
                return None, None, None

        ray_origin, ray_target, ray_direction = tool.Raycast.get_viewport_ray_data(context, event)

        objs_to_raycast = []
        for obj, bbox_2d in objs_2d_bbox:
            if obj.type in {"MESH", "EMPTY", "CURVE"} and bbox_2d:
                if tool.Raycast.intersect_mouse_2d_bounding_box(mouse_pos, bbox_2d, offset):
                    if obj.visible_in_viewport_get(
                        context.space_data
                    ):  # Check for local view and local collections for this viewport and object
                        objs_to_raycast.append(obj)

        # Polyline
        try:
            polyline_data = bpy.context.scene.BIMPolylineProperties.insertion_polyline[0]
            polyline_points = polyline_data.polyline_points
            last_polyline_point = polyline_points[len(polyline_points) - 1]
        except:
            polyline_points = []
            last_polyline_point = None
        if polyline_points:
            snap_points = tool.Raycast.ray_cast_to_polyline(context, event)
            if snap_points:
                for point in snap_points:
                    point["group"] = "Polyline"
                    detected_snaps.append(point)

        # Measure
        measure_data = context.scene.BIMPolylineProperties.measurement_polyline
        for measure in measure_data:
            measure_points = measure.polyline_points
            snap_points = tool.Raycast.ray_cast_to_measure(context, event, measure_points)
            if snap_points:
                for point in snap_points:
                    point["group"] = "Measure"
                    detected_snaps.append(point)

        # Edge-Vertex
        for obj in objs_to_raycast:
            if obj.type == "MESH":
                if len(obj.data.polygons) == 0:
                    snap_points = tool.Raycast.ray_cast_by_proximity(context, event, obj)
                    if snap_points:
                        for point in snap_points:
                            point["group"] = "Edge-Vertex"
                            detected_snaps.append(point)
            if obj.type == "CURVE":
                new_object = bpy.data.objects.new("new_object", obj.to_mesh().copy())
                snap_points = tool.Raycast.ray_cast_by_proximity(context, event, new_object)
                if snap_points:
                    for point in snap_points:
                        point["group"] = "Edge-Vertex"
                        detected_snaps.append(point)
            if obj.type == "EMPTY":
                snap_point = {
                    "type": "Vertex",
                    "point": obj.location,
                    "distance": 10,  # High value so it has low priority
                    "object": obj,
                    "group": "Edge-Vertex",
                }
                detected_snaps.append(snap_point)

        # Obj
        if (space.shading.type == "SOLID" and space.shading.show_xray) or (
            space.shading.type == "WIREFRAME" and space.shading.show_xray_wireframe
        ):
            results = []
            for obj in objs_to_raycast:
                results.append(cast_rays_to_single_object(obj, mouse_pos))
        else:
            results = []
            results.append(cast_rays_and_get_best_object(objs_to_raycast, mouse_pos))
        for result in results:
            snap_obj = result[0]
            hit = result[1]
            face_index = result[2]
            if hit is not None:
                snap_points = tool.Raycast.ray_cast_by_proximity(
                    context, event, snap_obj, snap_obj.data.polygons[face_index]
                )
                if snap_points:
                    for point in snap_points:
                        point["group"] = "Object"
                        detected_snaps.append(point)
                else:
                    snap_point = {
                        "point": hit,
                        "type": "Face",
                        "group": "Object",
                        "object": snap_obj,
                        "face_index": face_index,
                        "distance": 10,  # High value so it has low priority
                    }
                    detected_snaps.append(snap_point)

        # Axis and Plane
        elevation = tool.Ifc.get_object(tool.Root.get_default_container()).location.z

        plane_origin, plane_normal = select_plane_method()
        tool_state.plane_origin = plane_origin  # This will be used along with plane method

        intersection = tool.Raycast.ray_cast_to_plane(context, event, plane_origin, plane_normal)

        axis_start = None
        axis_end = None

        rot_intersection = None
        if not tool_state.plane_method:
            if tool_state.axis_method == "X":
                tool_state.snap_angle = 180
            if tool_state.axis_method == "Y":
                tool_state.snap_angle = 90
            if tool_state.axis_method == "Z":
                tool_state.snap_angle = 90
            if tool_state.axis_method:
                # Doesn't update snap_angle so that it keeps in the same axis
                rot_intersection, _, axis_start, axis_end = cls.snap_on_axis(intersection, tool_state)

        if tool_state.plane_method:
            if tool_state.plane_method in {"XY", "XZ"} and tool_state.axis_method == "X":
                tool_state.snap_angle = 180
            if tool_state.plane_method in {"XY", "YZ"} and tool_state.axis_method == "Y":
                tool_state.snap_angle = 90
            if tool_state.plane_method in {"YZ"} and tool_state.axis_method == "Z":
                tool_state.snap_angle = 180
            if tool_state.plane_method in {"XZ"} and tool_state.axis_method == "Z":
                tool_state.snap_angle = 90
            if tool_state.lock_axis or tool_state.axis_method:
                # Doesn't update snap_angle so that it keeps in the same axis
                rot_intersection, _, axis_start, axis_end = cls.snap_on_axis(intersection, tool_state)
            else:
                rot_intersection, tool_state.snap_angle, axis_start, axis_end = cls.snap_on_axis(
                    intersection, tool_state
                )

        if rot_intersection and polyline_points:
            snap_point = {
                "point": rot_intersection,
                "object": None,
                "group": "Axis",
                "type": "Axis",
                "axis_start": axis_start,
                "axis_end": axis_end,
                "distance": 10,  # High value so it has low priority
            }
            detected_snaps.append(snap_point)

        snap_point = {
            "point": intersection,
            "object": None,
            "group": "Plane",
            "type": "Plane",
            "distance": 10,  # High value so it has low priority
        }
        detected_snaps.append(snap_point)

        return detected_snaps

    @classmethod
    def select_snapping_points(cls, context, event, tool_state, detected_snaps):
        def filter_snapping_points_by_type(snapping_points):
            options = ["Plane", "Axis"]
            props = context.scene.BIMSnapProperties
            for prop in props.__annotations__.keys():
                if getattr(props, prop):
                    options.append(props.rna_type.properties[prop].name)

            filtered_points = [point for point in snapping_points if point["type"] in options]
            return filtered_points

        def filter_snapping_points_by_group(detected_snaps):
            options = ["Edge-Vertex", "Axis", "Plane"]
            props = context.scene.BIMSnapGroups
            for prop in props.__annotations__.keys():
                if getattr(props, prop):
                    options.append(props.rna_type.properties[prop].name)
            filtered_groups = [group for group in detected_snaps if group["group"] in options]
            return filtered_groups

        snaps_by_group = filter_snapping_points_by_group(detected_snaps)
        edges = []  # Get edges to create edge-intersection snap
        for snapping_point in snaps_by_group:
            if snapping_point["group"] in {"Polyline", "Measure", "Edge-Vertex", "Object"}:
                if snapping_point["type"] == "Edge":
                    edges.append(snapping_point)
            if snapping_point["group"] == "Axis":
                axis_start = snapping_point["axis_start"]
                axis_end = snapping_point["axis_end"]

        # Edges intersection snap
        if edges:
            snap_point = tool.Raycast.ray_cast_to_edge_intersection(context, event, edges)
            if snap_point:
                snaps_by_group.insert(0, snap_point)

        snaps_by_type = filter_snapping_points_by_type(snaps_by_group)
        snaps_by_type = sorted(snaps_by_type, key=lambda x: x["distance"])

        # Make Axis first priority
        if tool_state.lock_axis or tool_state.axis_method in {"X", "Y", "Z"}:
            cls.update_snapping_ref(snaps_by_type[0]["point"], snaps_by_type[0]["type"])
            for point in snaps_by_type:
                if point["type"] == "Axis":
                    if snaps_by_type[0]["type"] not in {"Axis", "Plane"}:
                        obj = snaps_by_type[0]["object"]
                        mixed_snap = cls.mix_snap_and_axis(snaps_by_type[0]["point"], axis_start, axis_end)
                        for mixed_point in mixed_snap:
                            snap_point = {
                                "point": mixed_point,
                                "type": "Mix",
                                "object": obj,
                            }
                            snaps_by_type.insert(0, snap_point)
                        cls.update_snapping_point(snap_point["point"], snap_point["type"])
                        return snaps_by_type
                    cls.update_snapping_point(point["point"], point["type"])
                    return snaps_by_type

        cls.update_snapping_point(snaps_by_type[0]["point"], snaps_by_type[0]["type"], snaps_by_type[0]["object"])
        return snaps_by_type

    @classmethod
    def modify_snapping_point_selection(cls, snapping_points, lock_axis=False):
        shifted_list = snapping_points[1:] + snapping_points[:1]
        if lock_axis:  # Will only cycle through mix or axis
            non_axis_snap = [point for point in snapping_points if point["type"] not in {"Axis", "Mix"}]
            axis_snap = [point for point in snapping_points if point["type"] in {"Axis", "Mix"}]
            shifted_list = axis_snap[1:] + axis_snap[:1]
            shifted_list.extend(non_axis_snap)

        cls.update_snapping_point(shifted_list[0]["point"], shifted_list[0]["type"])
        return shifted_list

"""calculation of mesh based features"""
from typing import Tuple, List, Any, Optional

import numpy as np
import numpy.typing
import pandas as pd
import trimesh
from lasso.dyna import D3plot, ArrayType

from mesh2vec.mesh2vec_exceptions import PointIdsMustBeUnqiueException


def quads_to_tris_feature_list(
    element_node_idxs: np.ndarray, feature_values: List[Any]
) -> Tuple[np.ndarray, np.ndarray]:
    """
    convert 4-node elements to 3-node elements
    works on node ids and on point positions
    supports a single feature (in a list)
    """
    is_quads, tri_faces = _quad_to_tris(element_node_idxs)

    tri_features_nested = [
        [feature_value, feature_value] if is_quad else [feature_value]
        for is_quad, feature_value in zip(is_quads, feature_values)
    ]
    tri_features = np.array(
        [tri_feature for tri_features in tri_features_nested for tri_feature in tri_features]
    )
    return tri_faces, tri_features


def _quad_to_tris(element_node_idxs: np.ndarray) -> Tuple[List[bool], np.ndarray]:
    if len(element_node_idxs.shape) == 3:  # points
        is_quads = [any(element[3] != element[2]) for element in element_node_idxs]
        tri_faces_nested = [
            [element[:3].tolist(), element[[0, 2, 3]].tolist()]
            if is_quad
            else [element[:3].tolist()]
            for is_quad, element in zip(is_quads, element_node_idxs)
        ]
    else:
        is_quads = [element[3] != element[2] for element in element_node_idxs]
        tri_faces_nested = [
            [element[:3].tolist(), element[[0, 2, 3]].tolist()]
            if is_quad
            else [element[:3].tolist()]
            for is_quad, element in zip(is_quads, element_node_idxs)
        ]
    tri_faces = np.array([tri_face for tri_faces in tri_faces_nested for tri_face in tri_faces])
    return is_quads, tri_faces


def quads_to_tris_df(
    element_node_idxs: np.ndarray, features: pd.DataFrame
) -> Tuple[np.ndarray, pd.DataFrame]:
    """
    convert 4-node elements to 3-node elements
    works on node ids and on point positions
    supports multiple features (in a dataframe)
    """
    is_quads, tri_faces = _quad_to_tris(element_node_idxs)

    tri_feature_dict = {}
    for k in features.columns:
        feature_values = features[k]
        tri_features_nested = [
            [feature_value, feature_value] if is_quad else [feature_value]
            for is_quad, feature_value in zip(is_quads, feature_values)
        ]
        tri_features = np.array(
            [tri_feature for tri_features in tri_features_nested for tri_feature in tri_features]
        )
        tri_feature_dict[k] = tri_features
    return tri_faces, pd.DataFrame(tri_feature_dict)


def area(element_node_idxs: np.ndarray, point_coordinates: np.ndarray) -> np.ndarray:
    """
    calculate the area of tri/quad elements
    """
    shell_elements = point_coordinates[element_node_idxs]
    tris, ids = quads_to_tris_feature_list(shell_elements, list(range(len(shell_elements))))
    vectors = np.diff(tris, axis=1)
    crosses = np.cross(vectors[:, 0], vectors[:, 1])
    tri_areas = (np.sum(crosses**2, axis=1) ** 0.5) * 0.5
    quad_areas = np.bincount(ids, weights=tri_areas)
    return quad_areas


def is_tri(element_node_idxs: np.ndarray) -> List[bool]:
    """
    check if type is triangle for all elements
    """
    return [element[3] == element[2] for element in element_node_idxs]


def num_border(element_node_idxs: np.ndarray) -> np.ndarray:
    """count number of borders (exclusive edges) of the element"""
    edges = np.array([element_node_idxs[:, ij] for ij in [[0, 1], [1, 2], [2, 3], [3, 0]]])
    flat_edges = np.concatenate(np.sort(edges, axis=2))
    _, indexes, counts = np.unique(flat_edges, return_counts=True, return_inverse=True, axis=0)
    counts_per_element_edge = counts[indexes]
    counts_per_element_edge = np.reshape(counts_per_element_edge, [4, -1]).T
    counts_per_element_edge[is_tri(element_node_idxs), 2] = 2  # set 4th edge to default count
    return 8 - np.sum(counts_per_element_edge, axis=1)  # each no-border quad has 4*2 edge counts


def midpoint(
    element_node_idxs: np.ndarray,
    point_coordinates: np.ndarray,
) -> np.ndarray:
    """calculate midpoint (mean center) of each element"""
    points = point_coordinates[element_node_idxs]
    points[is_tri(element_node_idxs), 3, :] = np.nan
    return np.nanmean(points, axis=1)


def _make_ids_unique(
    array: numpy.typing.NDArray[np.string_], element_node_idxs: np.ndarray, point_uid: np.ndarray
) -> numpy.typing.NDArray[np.string_]:
    """replace overlapping values in array by adding nodes ids to element id"""
    if len(array) == len(np.unique(array)):
        return array
    cumcounts = pd.DataFrame(array, columns=["ids"]).groupby("ids").cumcount().values
    return np.array(
        [
            old_id
            if postfix == 0
            else f"{old_id}_{point_uid[e[0]]}_{point_uid[e[1]]}_"
            f"{point_uid[e[2]]}_{point_uid[e[3]]}"
            for old_id, e, postfix in zip(array, element_node_idxs, cumcounts)
        ]
    )


class CaeShellMesh:
    """dataclass for points and elements"""

    point_coordinates: numpy.typing.NDArray[np.float_]  # (n_nodes, x_y_z)
    point_ids: numpy.typing.NDArray[np.string_]  # (n_nodes)
    element_ids: numpy.typing.NDArray[np.string_]  # (n_elements)

    # (n_elements, 4) - triangles have same value at 2 and 3
    element_node_idxs: numpy.typing.NDArray[np.int_]

    point_uid: numpy.typing.NDArray[np.string_]
    element_uid: numpy.typing.NDArray[np.string_]

    def __init__(
        self,
        point_coordinates: numpy.typing.NDArray[np.float_],
        point_ids: numpy.typing.NDArray[np.string_],
        element_ids: numpy.typing.NDArray[np.string_],
        element_node_idxs: numpy.typing.NDArray[np.int_],
    ):
        assert len(point_coordinates) == len(point_ids)

        if not element_node_idxs.shape[1] == 4:  # convert tri only to tri/quad
            element_node_idxs = np.hstack(
                [element_node_idxs, element_node_idxs[:, 2].reshape([-1, 1])]
            )
            assert element_node_idxs.shape[1] == 4

        self.point_coordinates = point_coordinates
        self.point_ids = point_ids
        self.element_ids = element_ids
        self.element_node_idxs = element_node_idxs

        self.point_uid = point_ids
        if not len(self.point_uid) == len(np.unique(self.point_uid)):
            raise PointIdsMustBeUnqiueException()
        self.element_uid = _make_ids_unique(
            self.element_ids, self.element_node_idxs, self.point_uid
        )

    @staticmethod
    def from_d3plot(d3plot_data: D3plot, partid: Optional[int] = None) -> "CaeShellMesh":
        """create CaeShellMesh from lasso D3plot"""
        if partid is not None:
            part_index = np.where(d3plot_data.arrays["part_ids"] == partid)[0]
            selected_part_ids = np.where(
                d3plot_data.arrays[ArrayType.element_shell_part_indexes] == part_index
            )
            elem_ids = np.array(
                [
                    f"{v}"
                    for v in d3plot_data.arrays[ArrayType.element_shell_ids][selected_part_ids]
                ]
            )
            elem_node_idxs = d3plot_data.arrays[ArrayType.element_shell_node_indexes][
                selected_part_ids
            ]

            pt_idx, new_elem_idx = np.unique(
                elem_node_idxs,
                return_inverse=True,
            )
            new_elem_idx = np.reshape(new_elem_idx, elem_node_idxs.shape)

            pnt_ids = np.array([f"{v}" for v in d3plot_data.arrays[ArrayType.node_ids][pt_idx]])
            point_coordinates = d3plot_data.arrays[ArrayType.node_coordinates][pt_idx]
            return CaeShellMesh(point_coordinates, pnt_ids, elem_ids, new_elem_idx)

        point_coordinates = d3plot_data.arrays[ArrayType.node_coordinates]
        pnt_ids = np.array([f"{v}" for v in d3plot_data.arrays[ArrayType.node_ids]])
        elem_ids = np.array([f"{v}" for v in d3plot_data.arrays[ArrayType.element_shell_ids]])
        elem_node_idxs = d3plot_data.arrays[ArrayType.element_shell_node_indexes]
        return CaeShellMesh(point_coordinates, pnt_ids, elem_ids, elem_node_idxs)

    @staticmethod
    def from_trimesh(trimesh_mesh: trimesh.Trimesh) -> "CaeShellMesh":
        """create CaeShellMesh from trimesh"""
        point_coordinates = np.array(trimesh_mesh.vertices)
        pnt_ids = np.array([f"pt_{i}" for i, _ in enumerate(trimesh_mesh.vertices)])
        elem_ids = np.array([f"face_{i}" for i, _ in enumerate(trimesh_mesh.faces)])

        # add 4th column for quad compatibility
        elem_node_idxs = np.array(trimesh_mesh.faces[:, [0, 1, 2, 2]])

        return CaeShellMesh(point_coordinates, pnt_ids, elem_ids, elem_node_idxs)

    @staticmethod
    def from_ansa_json(elements: List[Any], nodes: List[Any]) -> "CaeShellMesh":
        """create CaeShellMesh from ansa exported json"""
        pnt_ids = np.array([str(node["__id__"]) for node in nodes])
        pnt_idx = {node["__id__"]: i for i, node in enumerate(nodes)}
        point_coordinates = np.array([[node["X"], node["Y"], node["Z"]] for node in nodes])
        elem_ids = np.array([str(element["__id__"]) for element in elements])
        elements = [
            element if "N4" in element.keys() else {**element, "N4": element["N3"]}
            for element in elements
        ]
        elem_node_idxs = np.array(
            [[pnt_idx[element[f"N{i}"]] for i in range(1, 5)] for element in elements]
        )  # duplicate ids allowed?
        return CaeShellMesh(point_coordinates, pnt_ids, elem_ids, elem_node_idxs)

    @staticmethod
    def from_keyfile(keyfile: str, partid: str = "") -> "CaeShellMesh":
        """
        create CaeShellMesh from keyfile

        Args:
            keyfile: path to LSDYNA keyfile in fixed column format
            partid: part id to use for hypergraph generation

        Example:
        >>> from mesh2vec.mesh_features import CaeShellMesh
        >>> mesh = CaeShellMesh.from_keyfile("data/hat/Hatprofile.k")
        >>> print(mesh.point_coordinates.shape)
        (6400, 3)
        """

        def parse_contents(file_contents):
            lines = file_contents.split("\n")
            current_section = ""

            point_coordinates = []
            pnt_ids = []

            elem_ids = []
            elem_node_ids = []
            thickcard_options_set = set(["THICKNESS", "BETA", "MCID"])
            for line in lines:
                if line.startswith("*"):
                    current_section = line.split()[0].upper()
                    current_section_options = set(current_section.split('_')[1:])
                    current_section_lines_per_entry = 1
                    current_section_lineno = 0
                    continue
                if line.startswith("$"):  # comment
                    continue
                if current_section == "*NODE":
                    try:
                        point_coordinates.append([float(line[8+i*16:8+(i+1)*16]) for i in range(3)])
                        pnt_ids.append(line[:8].strip())
                    except:
                        pass
                elif current_section.startswith("*ELEMENT_SHELL"):
                    

                    if current_section_lineno % current_section_lines_per_entry == 0:
                        if partid == "" or partid == line[8:16].strip():
                            node_ids = [line[16+i*8:16+(i+1)*8].strip() for i in range(8)]
                            node_ids = [node_id for node_id in node_ids if len(node_id) > 0 and node_id != "0"]
                            # TODO: Check for unhandled options, e.g. COMPOSITE, DOF
                            if current_section_lineno == 0:
                                if len(current_section_options & thickcard_options_set) > 0:
                                    current_section_lines_per_entry += 1 # skip thickness card
                                    if len(node_ids) > 4:
                                        current_section_lines_per_entry += 1 # skip additional thickness card for mid-side nodes
                                if "OFFSET" in current_section_options:
                                        current_section_lines_per_entry += 1 # skip offset card
                            elem_node_ids.append([node_id for node_id in node_ids if len(node_id) > 0])
                            if node_ids[0] == 1.0:
                                print("HERE")
                            elem_ids.append(line[:8].strip())
                    current_section_lineno += 1

            pnt_idx = {pnt_id: i for i, pnt_id in enumerate(pnt_ids)}

            elem_node_idx = np.array(
                [[pnt_idx[elem_node_id[i]] for i in range(4)] for elem_node_id in elem_node_ids]
            )

            return point_coordinates, pnt_ids, elem_ids, elem_node_idx

        with open(keyfile, "r", encoding="utf-8") as file:
            file_contents = file.read()
        point_coordinates, pnt_ids, elem_ids, elem_node_idx = parse_contents(file_contents)

        return CaeShellMesh(
            np.array(point_coordinates),
            np.array(pnt_ids),
            np.array(elem_ids),
            np.array(elem_node_idx),
        )

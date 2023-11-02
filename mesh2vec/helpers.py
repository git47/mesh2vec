"""helper functions"""
from typing import OrderedDict, List, Tuple, Dict

import numpy as np
from scipy.sparse import csr_array, coo_array, eye, csr_matrix, lil_matrix
import igraph as ip
from abc import ABC, abstractmethod
import time

"""
Use strategy to implement multiple adjacency finding algorithms
"""


class AbstractAdjacencyStrategy(ABC):
    @abstractmethod
    def calc_adjacencies(
        self, hyper_edges_idx: OrderedDict[str, List[int]], max_distance: int
    ) -> Tuple[Dict[int, csr_array], Dict[int, csr_array]]:
        pass


class MatMulAdjacency(AbstractAdjacencyStrategy):
    def calc_adjacencies(
        self, hyper_edges_idx: OrderedDict[str, List[int]], max_distance: int
    ) -> Tuple[Dict[int, csr_array], Dict[int, csr_array]]:
        """calc adjacencies for hyper nodes with matrix multiplication to find adjacent nodes for a given distance"""
        # vtx_connectivity: holds for each vtx all connected vtx

        timer = time.time()
        adjacency_list = []
        for vtxs in hyper_edges_idx.values():
            for vtx_a in vtxs:
                for vtx_b in vtxs:
                    adjacency_list.append([vtx_a, vtx_b])
        adjacency_list_np = np.unique(np.array(adjacency_list), axis=0)
        print("ADJACENCY LIST first element: ", adjacency_list_np[0])

        # adjacency matrix
        n_vtx = max(max(v) for v in hyper_edges_idx.values()) + 1
        data = np.array([1] * len(adjacency_list_np))
        adjacency_matrix = coo_array(
            (data, (adjacency_list_np[:, 1], adjacency_list_np[:, 0])), shape=(n_vtx, n_vtx)
        ).tocsr()

        print("ADJACENCY LIMATRIX shape: ", adjacency_matrix.shape)

        # neighbors
        adjacency_matrix_powers = {1: adjacency_matrix}
        adjacency_matrix_powers_exclusive = {
            1: adjacency_matrix - csr_array(eye(n_vtx, dtype=int))
        }
        print("POWERS BEGINNING : ", adjacency_matrix_powers)
        print("POWERS EXCLUSIVE BEGINNING: ", adjacency_matrix_powers_exclusive)
        for i in range(2, max_distance + 1):
            adjacency_matrix_powers[i] = adjacency_matrix_powers[i - 1] @ adjacency_matrix
            adjacency_matrix_powers[i].data = np.array([1] * adjacency_matrix_powers[i].nnz)
            exclusive = (adjacency_matrix_powers[i] - adjacency_matrix_powers[i - 1]).tocsr()
            adjacency_matrix_powers_exclusive[i] = exclusive

            print("POWERS BEGINNING ", str(i), " : ", adjacency_matrix_powers)
            print("POWERS EXCLUSIVE", str(i), " : ", adjacency_matrix_powers_exclusive)

        print("THIS TOOK: ", time.time() - timer)

        return adjacency_matrix_powers, adjacency_matrix_powers_exclusive


class BFSAdjacency(AbstractAdjacencyStrategy):
    def calc_adjacencies(
        self, hyper_edges_idx: OrderedDict[str, List[int]], max_distance: int
    ) -> Tuple[Dict[int, csr_array], Dict[int, csr_array]]:
        # convert hyper edges to graph; hyper_edges: key -> node, values -> edges to directly connected nodes
        # as nodes are already integers, create graph from scratch
        # note: some nodes are integers written as strings -> conversion necessary
        timer = time.time()
        graph = ip.Graph(
            edges=[
                (int(vertice), int(connected_vertice))
                for vertice in hyper_edges_idx.keys()
                for connected_vertice in hyper_edges_idx[vertice]
                if (
                    (type(vertice) in [str, int] or np.issubdtype(vertice.dtype, np.str_))
                    and (
                        type(connected_vertice) in [str, int]
                        or np.issubdtype(connected_vertice.dtype, np.str_)
                    )
                )
            ]
        )

        n_vtx = len(graph.vs)
        print("NUMBER OF VERTICES: ",n_vtx)

        adjacency_matrix_powers = {1: graph.get_adjacency_sparse()}
        adjacency_matrix_powers_exclusive = {
            1: graph.get_adjacency_sparse() - csr_matrix(eye(n_vtx, dtype=int))
        }

        print("POWERS BEGINNING : ", adjacency_matrix_powers)
        print("POWERS EXCLUSIVE BEGINNING: ", adjacency_matrix_powers_exclusive)
        ####################################################
        # General idea: BFS for each vertex for each depth #
        ####################################################

        # convert once instead of every time in loop
        vertices = [int(vertice) for vertice in hyper_edges_idx.keys()]

        for depth in range(2, max_distance + 1):
            adjacency_matrix = lil_matrix((n_vtx, n_vtx))
            # grab the last cumulative matrix that we calculated as our base; LIL are more efficient than csr matrices
            cumulative_matrix = adjacency_matrix_powers[depth - 1].tolil()
            print("HAHA")
            for vertex in vertices:
                queue = [vertex]
                visited = set()
                current_depth = 0

                while queue and current_depth <= depth:
                    next_level = set()
                    for v in queue:
                        if v not in visited:
                            visited.add(v)
                            adjacency_matrix[vertex, v] = 1
                            cumulative_matrix[vertex, v] = 1
                            neighbors = graph.neighbors(v)
                            next_level.update(neighbors)
                    queue = list(next_level)
                    current_depth += 1
            print("BOO")
            # convert powers matrix from previous depth from lil to csr, as we will not look at it anymore
            adjacency_matrix_powers[depth - 1] = adjacency_matrix_powers[depth - 1].tocsr() - csr_matrix(eye(n_vtx, dtype=int))

            print("LAUTRE")
            # add adjacency matrix for specific depth
            lil_result = adjacency_matrix - lil_matrix(eye(n_vtx, dtype=int))
            adjacency_matrix_powers_exclusive[depth] = csr_matrix(lil_result)

            print("HAMBURG")
            # add cumulative to powers, not in csr yet; we need to use it in the next iteration
            adjacency_matrix_powers[depth] = cumulative_matrix

            print("POWERS BEGINNING ", str(depth), " : ", adjacency_matrix_powers)
            print("POWERS EXCLUSIVE", str(depth), " : ", adjacency_matrix_powers_exclusive)

        # convert last cumulative matrix to CSR
        # adjacency_matrix_powers[max_distance] = csr_matrix(adjacency_matrix_powers[depth - 1]) - csr_matrix(eye(n_vtx, dtype=int))
        print("THIS TOOK: ", time.time() - timer)

        return adjacency_matrix_powers, adjacency_matrix_powers_exclusive

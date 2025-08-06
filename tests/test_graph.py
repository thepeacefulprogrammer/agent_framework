import pytest
from minimal_agent_framework import Graph, Node

def test_graph_creation():
    graph = Graph()
    assert graph is not None
    assert isinstance(graph, Graph)

def test_graph_has_nodes_list():
    graph = Graph()
    assert hasattr(graph, 'nodes')
    assert isinstance(graph.nodes, list)
    assert len(graph.nodes) == 0


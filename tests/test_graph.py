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

def test_node_creation():
    node = Node()
    assert node is not None
    assert isinstance(node, Node)

def test_add_node_to_graph():
    graph = Graph()
    node = Node()
    graph.nodes.append(node)
    assert len(graph.nodes) == 1
    assert graph.nodes[0] is node
    assert isinstance(graph.nodes[0], Node)
import pytest
from minimal_agent_framework import Graph

def test_graph_creation():
    graph = Graph()
    assert graph is not None
    assert isinstance(graph, Graph)
from unittest.mock import MagicMock
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

def test_graph_has_starting_node_attribute():
    graph = Graph()
    assert hasattr(graph, 'starting_node')
    assert graph.starting_node is None
    
def test_starting_node_starts_with_graph_run():
    graph = Graph()
    mock_node = MagicMock()
    graph.nodes.append(mock_node)
    graph.run(mock_node)
    mock_node.execute.assert_called_once()

def test_starting_node_fails_if_node_has_not_been_added():
    graph = Graph()
    mock_node = MagicMock()
    other_node = MagicMock()
    graph.nodes.append(other_node)
    try:
        graph.run(mock_node)
        assert False, "Expected ValueError when starting node is not in graph"
    except ValueError as e:
        assert str(e) == "Starting node must be part of the graph's nodes."

def test_running_node_returns_next_node_name_to_run():
    graph = Graph()
    node_1 = Node().name("node_1").routes([{"node_2": "default"}])
    node_2 = Node().name("node_2")
    graph.nodes.append(node_1)
    graph.nodes.append(node_2)
    graph.run(node_1)
    assert node_1.execute() == "node_2"

def test_graph_executes_next_node():
    graph = Graph()
    mock_node_1 = MagicMock()
    mock_node_2 = MagicMock()
    mock_node_1._name = "node_1"
    mock_node_2._name = "node_2"
    mock_node_1.execute.return_value = "node_2"
    mock_node_2.execute.return_value = ""

    graph.nodes.append(mock_node_1)
    graph.nodes.append(mock_node_2)
    graph.run(mock_node_1)
    mock_node_1.execute.assert_called_once()
    mock_node_2.execute.assert_called_once()

def test_node_executes_pre_and_post_functions():

    mock_pre = MagicMock()
    mock_post = MagicMock()

    graph = Graph()
    node_1 = Node().name("node_1").routes([{"node_2": "default"}]).pre(mock_pre).post(mock_post)
    node_2 = Node().name("node_2")


    graph.nodes.append(node_1)
    graph.nodes.append(node_2)
    graph.run(node_1)

    mock_pre.assert_called_once()
    mock_post.assert_called_once()

